# -*- coding: utf-8 -*-
"""Plan de chargement d'une cale : poser, déplacer, tourner, épingler.

Vue de dessus à l'échelle, sur le plan de cale s'il y en a un. Chaque charge
est un rectangle qu'on saisit à la souris. Ce qui dépasse du bord ou chevauche
une autre charge est dessiné en rouge et listé : on travaille son plan avant le
chargement, l'erreur se voit tout de suite.

Le solveur (`carene.core.stowage`) peut remplir la cale depuis le manifeste ;
les charges épinglées ne bougent jamais.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QImage, QPainter, QPen, QPolygonF, QTransform,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .core.cargo_model import (
    CATEGORIES, COULEURS_CATEGORIE, Catalogue, CargoType, Placement, couleur_hex,
    mention_debord, rect_occupe, se_touchent,
)
from .core.stowage import (
    ASSIETTE_GM, AUTO, CAPACITE, DEBORD_JEU_M, Hold, JEU_M, LONGITUDINALE,
    Packer, Reglages,
    TRANSVERSALE, aimanter, bornes_polygone, charge_pont_ok, est_epontille,
    gerbage_refuse, hauteur_libre_de, meme_pile, niveaux_possibles,
    rect_dans_polygone, rect_epontille, trop_haut,
)
from .project import epontille_fixe
from .saisie import SpinNombre

PAS_SNAP = 0.05

# Comment se lit une DISPOSITION sous le bouton « Remplir » — dans quel sens
# la cale se remplit, pas dans quel sens sont posés les colis. Le mot est celui
# de la liste du répartiteur : le bord doit reconnaître ce qu'il y a coché.
DISPOSITION_DITE = {AUTO: "automatique", LONGITUDINALE: "longitudinale",
                    TRANSVERSALE: "transversale"}


def reglages_du_remplissage(win, jeu_m=0.0):
    """Les réglages avec lesquels le plan de cale remplit une cale.

    Ce sont ceux du DERNIER passage du répartiteur (`win.derniers_reglages_
    solveur`), le jeu du plan de cale en plus. Sans cela les deux chemins
    posent différemment alors qu'ils appellent le même calepineur : le
    répartiteur reçoit la disposition, la rotation, la gîte et l'assiette que
    le bord a réglées, et le plan de cale repartait chaque fois des valeurs
    d'usine — sur une cale du navire de référence et 40 palettes, aucun colis au même
    endroit dès qu'une disposition est imposée.

    Faute de passage du répartiteur, on garde le comportement d'avant :
    remplir CETTE cale au plus, ce qui est bien ce que le bouton promet.

    Le jeu de la molette ne descend jamais sous la marge de calepinage du
    moteur (`DEBORD_JEU_M`, la moitié de l'écart `JEU_M` que le calepineur
    laisse entre deux colis) : cette marge-là n'est pas un choix d'arrimage,
    c'est ce qui garantit que deux emprises ne se touchent pas exactement.
    Molette à zéro, on retombe donc pile sur ce que fait le répartiteur ;
    molette à 5 cm, chaque colis déborde de 5 cm de chaque côté et le
    calepineur laisse 10 cm entre deux voisins (D-64)."""
    import dataclasses
    jeu = max(float(jeu_m), DEBORD_JEU_M)
    reg = getattr(win, "derniers_reglages_solveur", None)
    if isinstance(reg, Reglages):
        return dataclasses.replace(reg, jeu_m=jeu)
    return Reglages(objectif=CAPACITE, jeu_m=jeu)


def dire_reglages(reg, du_solveur):
    """Ce qu'on annonce sous le bouton « Remplir » : avec quoi ça remplit.

    Le bord s'est étonné que le plan de cale et le répartiteur ne posent pas
    pareil ; qu'il puisse LIRE les réglages employés vaut mieux que de le lui
    promettre."""
    bouts = [f"disposition : "
             f"{DISPOSITION_DITE.get(reg.disposition, reg.disposition)}"]
    if reg.rotation_permise is False:
        bouts.append("sans rotation")
    # Les permissions qui CHANGENT ce qu'on voit se disent, et seulement
    # elles : une barre qui récite douze réglages ne se lit plus. Cochées
    # d'office, elles ne s'annoncent pas ; décochées, elles expliquent
    # pourquoi la cale se remplit moins qu'hier.
    if not getattr(reg, "empiler", True):
        bouts.append("sans empilement")
    if not getattr(reg, "melanger_lots", True):
        bouts.append("lots non mélangés")
    bouts.append("gîte cherchée" if reg.equilibrer_tcg else "gîte laissée")
    if not getattr(reg, "viser_assiette", True):
        bouts.append("assiette non visée")
    elif reg.objectif == ASSIETTE_GM:
        bouts.append(f"assiette {reg.assiette_cible_m:+.2f} m".replace(".", ","))
    else:
        bouts.append("au plus")
    bouts.append(f"jeu {reg.jeu_m or 0.0:.2f} m".replace(".", ","))
    tete = ("Remplit avec les réglages du répartiteur"
            if du_solveur else
            "Remplit avec les réglages d'usine (le répartiteur n'a pas encore "
            "tourné)")
    return f"{tete} — " + " · ".join(bouts) + "."


def pivot_en_place(pl):
    """Le quart de tour d'un colis DÉJÀ POSÉ : `(x, y, rot)` pour qu'il pivote
    autour de son CENTRE.

    « Quand un colis est posé, et que la souris est dessus, on peut le retirer
    de la cale, mais on ne peut pas le tourner. » Il tournait pourtant — mais
    autour de son coin bas-gauche, puisque c'est ce que `Placement.x/y`
    désigne. Une palette de 1,20 × 0,80 se décalait donc de 20 cm en long et
    de 20 cm en travers à chaque quart de tour : dans une cale rangée, elle
    mordait aussitôt sa voisine, la pose était refusée, et rien ne bougeait à
    l'écran. Or tourner un colis posé, à bord, c'est le faire pivoter LÀ OÙ IL
    EST : on garde son centre et on échange ses côtés.

    Fonction pure : elle ne pose rien et ne vérifie rien — c'est `appliquer`
    qui reste seul juge de la pose (D-27)."""
    cx, cy = pl.centre
    rot = 0 if pl.rot % 180 else 90
    dx, dy = ((pl.largeur_m, pl.longueur_m) if rot == 90
              else (pl.longueur_m, pl.largeur_m))
    return round(cx - dx / 2, 6), round(cy - dy / 2, 6), rot


def _couleur(p):
    return QColor(couleur_hex(p))


def _card(title):
    frame = QFrame()
    frame.setObjectName("card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(9, 7, 9, 9)
    lay.setSpacing(7)
    if title:
        t = QLabel(title)
        t.setObjectName("cardTitle")
        lay.addWidget(t)
    return frame, lay


def _dessiner_obstacles(p, obstacles, to_px, hauteurs=True, interdites=True):
    """Les zones particulières de la cale, visibles sur le plan de cale comme
    sur le plan de pont :

    - zones INTERDITES (épontille fixe, descente, puits…) : quadrillage serré
      gris foncé, trait plein, avec leur nom — rien ne s'y pose, JAMAIS ;
    - zones de HAUTEUR RÉDUITE (« hauteur libre 1.70 m ») : un calque hachuré
      en biais dans la teinte d'alerte, avec la hauteur écrite — on y pose, et
      une pile trop haute y est cerclée de rouge (D-12).

    Les deux natures ne se dessinent plus de la même façon : un mur et un
    plafond bas se lisaient l'un comme l'autre en hachures, et l'officier ne
    savait pas d'un coup d'œil ce qui l'empêchait de poser. Le mur est
    quadrillé et cerné de plein, le plafond bas reste tireté et en biais.

    `hauteurs` et `interdites` disent quel calque dessiner : la vue de pose
    laisse éteindre celui des hauteurs pour dégager la fenêtre (les zones
    interdites, elles, se dessinent toujours — on ne masque pas un mur)."""
    f = p.font()
    for o in obstacles:
        if len(o) < 4:
            continue
        libre = hauteur_libre_de(o)
        if not (hauteurs if libre > 0 else interdites):
            continue
        x0, y0, x1, y1 = (float(v) for v in o[:4])
        ax, ay = to_px(min(x0, x1), max(y0, y1))
        bx, by = to_px(max(x0, x1), min(y0, y1))
        rect = QRectF(ax, ay, bx - ax, by - ay)
        if libre > 0:
            bord = QColor(theme.WARN)
            pen = QPen(bord, 1.1)
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(QBrush(bord, Qt.BrushStyle.FDiagPattern))
            p.drawRect(rect)
            if rect.width() > 30 and rect.height() > 12:
                fb = QFont(f)
                fb.setPointSize(8)
                fb.setBold(True)
                p.setFont(fb)
                p.setPen(bord.darker(125))
                txt = f"libre {libre:.2f} m" if rect.width() > 70 else f"{libre:.2f} m"
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, txt)
                p.setFont(f)
            continue
        mur = QColor(theme.TEXT_DIM)
        p.setPen(QPen(mur, 1.4))
        p.setBrush(QBrush(mur, Qt.BrushStyle.DiagCrossPattern))
        p.drawRect(rect)
        nom = str(o[4]) if len(o) > 4 and o[4] else "zone interdite"
        if rect.width() > 34 and rect.height() > 12:
            fb = QFont(f)
            fb.setPointSize(7)
            fb.setBold(True)
            p.setFont(fb)
            p.setPen(mur.darker(130))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, nom)
            p.setFont(f)


def _obstacles_actifs(capacity, en_place=()):
    """Les zones qui interdisent la pose dans cette cale ici et maintenant.

    Passe par `Capacity.obstacles_actifs` quand la cale en est une ; sinon
    (une cale bricolée dans un test) on retombe sur ses seuls obstacles."""
    f = getattr(capacity, "obstacles_actifs", None)
    if callable(f):
        return f(en_place)
    return [list(o) for o in (getattr(capacity, "obstacles", []) or [])]


def _motif_obstacle(obstacle) -> str:
    """Pourquoi cette emprise est refusée, dit comme l'officier le lirait.

    Une épontille se nomme : « épontille AR bâbord en place ». Il doit être
    clair que c'est une pièce qu'on peut déposer, pas une cloison."""
    nom = (obstacle[4] if len(obstacle) > 4 and obstacle[4] else "")
    if est_epontille(obstacle):
        return f"épontille « {nom or 'sans nom'} » en place"
    return f"empiète sur « {nom or 'zone interdite'} »"


def _dessiner_epontilles(p, capacity, en_place, to_px):
    """Les épontilles de la cale, sur le plan de cale comme sur le plan de
    pont. Une épontille FIXE se dessine « en place », toujours.

    Deux états, et la différence doit sauter aux yeux :

    - EN PLACE : trait plein, croix pleine — c'est un mur, rien ne s'y pose ;
    - déposée : le même repère en pointillé pâle, pour qu'on voie où elle
      POURRAIT aller sans que le logiciel refuse quoi que ce soit.

    Le repère (carré barré d'une croix) n'a rien d'un colis : une épontille
    n'est pas de la marchandise, elle ne doit jamais se lire comme telle."""
    ids = set(en_place or ())
    f = p.font()
    for e in getattr(capacity, "epontilles", []) or []:
        x0, y0, x1, y1 = rect_epontille(e)[:4]
        ax, ay = to_px(x0, max(y0, y1))
        bx, by = to_px(x1, min(y0, y1))
        rect = QRectF(ax, ay, bx - ax, by - ay).normalized()
        if rect.width() < 4:
            rect.adjust(-(4 - rect.width()) / 2, 0, (4 - rect.width()) / 2, 0)
        if rect.height() < 4:
            rect.adjust(0, -(4 - rect.height()) / 2, 0, (4 - rect.height()) / 2)
        # une épontille FIXE est toujours en place : structure, comme un mur
        pose = e.get("id") in ids or epontille_fixe(e)
        col = QColor(theme.DECK_LINE)
        if pose:
            fond = QColor(col)
            fond.setAlpha(150)
            p.setBrush(QBrush(fond))
            pen = QPen(col.darker(130), 1.8)
        else:
            fond = QColor(col)
            fond.setAlpha(28)
            p.setBrush(QBrush(fond))
            pen = QPen(col, 1.2)
            pen.setStyle(Qt.PenStyle.DotLine)
        p.setPen(pen)
        p.drawRect(rect)
        p.drawLine(rect.topLeft(), rect.bottomRight())
        p.drawLine(rect.topRight(), rect.bottomLeft())
        nom = str(e.get("nom") or "épontille")
        fb = QFont(f)
        fb.setPointSize(7)
        fb.setBold(pose)
        p.setFont(fb)
        p.setPen(QPen(col.darker(150) if pose else QColor(theme.TEXT_FAINT)))
        p.drawText(QRectF(rect.left() - 40, rect.bottom() + 1,
                          rect.width() + 80, 12),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                   nom if pose else f"({nom})")
        p.setFont(f)


def _dessiner_zones_charge(p, zones, to_px, defaut_t_m2=0.0):
    """Calque des charges admissibles : zones teintées, non bloquantes, avec
    leur valeur — la cale garde `defaut_t_m2` partout ailleurs."""
    f = p.font()
    for z in zones:
        pts = z.get("points", [])
        if len(pts) < 3:
            continue
        v = float(z.get("t_m2", 0.0))
        poly = QPolygonF([QPointF(*to_px(x, y)) for x, y in pts])
        # plus fort que la cale : vert ; plus faible : orange
        if defaut_t_m2 > 0 and v < defaut_t_m2 - 1e-9:
            teinte, bord = QColor(235, 150, 40, 55), QColor(200, 120, 20, 170)
        else:
            teinte, bord = QColor(60, 170, 90, 45), QColor(40, 140, 70, 170)
        pen = QPen(bord, 1.2)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(teinte)
        p.drawPolygon(poly)
        r = poly.boundingRect()
        if r.width() > 40 and r.height() > 14:
            fb = QFont(f)
            fb.setPointSize(8)
            fb.setBold(True)
            p.setFont(fb)
            p.setPen(bord.darker(130))
            nom = z.get("nom") or ""
            txt = f"{v:g} t/m²" + (f" — {nom}" if nom and r.width() > 140 else "")
            p.drawText(r.adjusted(4, 2, -4, -2), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, txt)
            p.setFont(f)


def _dessiner_annotations(p, annotations, to_px):
    """LE CALQUE D'INFORMATION du pont (`Deck.annotations`), tel qu'il a été
    décalqué : traits, points repérés, textes.

    Il ne contraint RIEN et ne se clique pas : c'est le décalque du bord —
    clés de saisissage, descente, prise de courant, remarque — qu'on veut
    lire en posant, sans qu'aucun calcul n'en dépende. Il se dessine donc
    sous les colis et en trait fin : il informe, il n'encombre pas.

    Quatre formes, celles du modèle : « trait » (polyligne), « polygone »
    (fermé, à peine teinté), « point » (une croix et son libellé), « texte »
    (le libellé seul, à l'endroit donné)."""
    f = p.font()
    fa = QFont(f)
    fa.setPointSize(8)
    for a in annotations or []:
        if not isinstance(a, dict):
            continue
        pts = [q for q in (a.get("points") or []) if len(q) >= 2]
        if not pts:
            continue
        # sans couleur donnée, celle des traits de pont : le calque doit se
        # distinguer des cales sans crier plus fort qu'elles
        col = QColor(a.get("couleur") or theme.CONTOUR)
        if not col.isValid():
            col = QColor(theme.CONTOUR)
        texte = str(a.get("texte") or "")
        genre = str(a.get("type") or "trait")
        p.setPen(QPen(col, 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setFont(fa)
        if genre == "trait" and len(pts) >= 2:
            poly = QPolygonF([QPointF(*to_px(q[0], q[1])) for q in pts])
            p.drawPolyline(poly)
            if texte:
                ux, uy = to_px(pts[0][0], pts[0][1])
                p.drawText(int(ux) + 4, int(uy) - 3, texte)
        elif genre == "polygone" and len(pts) >= 3:
            # fermé et à peine teinté : une surface qu'on repère, pas un mur
            poly = QPolygonF([QPointF(*to_px(q[0], q[1])) for q in pts])
            fond = QColor(col)
            fond.setAlpha(28)
            p.setBrush(fond)
            p.drawPolygon(poly)
            p.setBrush(Qt.BrushStyle.NoBrush)
            if texte:
                ux, uy = to_px(pts[0][0], pts[0][1])
                p.drawText(int(ux) + 4, int(uy) - 3, texte)
        elif genre == "point":
            ux, uy = to_px(pts[0][0], pts[0][1])
            p.drawLine(int(ux) - 4, int(uy), int(ux) + 4, int(uy))
            p.drawLine(int(ux), int(uy) - 4, int(ux), int(uy) + 4)
            if texte:
                p.drawText(int(ux) + 6, int(uy) - 3, texte)
        elif genre == "texte" and texte:
            ux, uy = to_px(pts[0][0], pts[0][1])
            p.drawText(int(ux), int(uy), texte)
        p.setFont(f)


def _etiquette_pile(p, rect, pl):
    """Le nom du colis dans son rectangle et, pour une pile, son compte « ×3 »
    — le compte passe avant le nom : sur un plan serré, savoir qu'on a trois
    palettes l'une sur l'autre compte plus que lire « Palette Europe »."""
    if rect.height() <= 12 or rect.width() <= 14:
        return
    p.setPen(QColor("#ffffff"))
    m = p.fontMetrics()
    pile = f"×{pl.niveaux}" if pl.niveaux > 1 else ""
    if not pile:
        if rect.width() > 26:
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                       m.elidedText(pl.nom, Qt.TextElideMode.ElideRight,
                                    int(rect.width()) - 4))
        return
    largeur_pile = m.horizontalAdvance(pile)
    reste = int(rect.width()) - largeur_pile - 8
    if reste > 18:
        nom = m.elidedText(pl.nom, Qt.TextElideMode.ElideRight, reste)
        p.drawText(rect.adjusted(3, 0, -largeur_pile - 5, 0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, nom)
        p.drawText(rect.adjusted(0, 0, -3, 0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, pile)
    elif rect.width() > largeur_pile + 2:
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, pile)


class StowCanvas(QWidget):
    """Vue de dessus de la cale : rectangles manipulables à la souris."""

    changed = Signal()
    selection_changed = Signal(object)
    refuse = Signal(str)                  # une pose a été annulée, et pourquoi

    def __init__(self, capacity, placements, parent=None):
        super().__init__(parent)
        self.capacity = capacity
        self.placements = placements          # liste vivante, modifiée en place
        self.selected = None
        self.setMinimumSize(520, 340)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._drag = None                     # (placement, dx, dy, départ)
        self.aimantation = True               # coller aux voisins et aux parois
        # jeu d'arrimage : ce qu'on laisse VOLONTAIREMENT entre deux colis
        # (saisines, fourches). La boîte le reprend de la vue Chargement, où
        # le bord l'a réglé — un seul jeu pour tout le navire ouvert (D-39).
        self.jeu_m = 0.0
        # Épontilles MISES EN PLACE à ce point (identifiants) : la cale les
        # porte toutes, le chargement dit lesquelles sont posées. La boîte
        # les recopie ici depuis la condition (voir StowEditorDialog).
        self.epontilles_en_place = set()
        self._image = None
        self.reload_image()

    # ------------------------------------------------------------- fond
    def reload_image(self):
        self._image = None
        plan = getattr(self.capacity, "plan", None)
        if plan and plan.image_path and os.path.exists(plan.image_path) \
                and plan.calibration.valid:
            img = QImage(plan.image_path)
            if not img.isNull():
                self._image = img
        self.update()

    # ------------------------------------------------------------- repère
    def _geom(self):
        pts = self.capacity.points
        if len(pts) < 3:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ox, oy = min(xs), min(ys)
        span_x, span_y = max(xs) - ox, max(ys) - oy
        if span_x <= 0 or span_y <= 0:
            return None
        pad = 28
        w = max(1.0, self.width() - 2 * pad)
        h = max(1.0, self.height() - 2 * pad)
        scale = min(w / span_x, h / span_y)
        left = pad + (w - span_x * scale) / 2
        top = pad + (h - span_y * scale) / 2
        return scale, left, top, ox, oy, span_x, span_y

    def to_px(self, x, y, geom):
        scale, left, top, ox, oy, _sx, span_y = geom
        return left + (x - ox) * scale, top + (span_y - (y - oy)) * scale

    def to_ship(self, px, py, geom):
        scale, left, top, ox, oy, _sx, span_y = geom
        return ox + (px - left) / scale, oy + span_y - (py - top) / scale

    # ------------------------------------------------------------- validité
    def pose_refusee(self, pl):
        """Raison de refuser cette place au sol, ou None si elle tient.

        Ce qui est jugé est la PLACE OCCUPÉE — l'emprise, plus le débord du
        lot de chaque côté (D-39), plus le jeu d'arrimage réglé à la molette
        (D-64) — comme sur le plan de pont : un même colis ne peut pas être
        refusé d'un côté et accepté de l'autre (D-27)."""
        jeu = max(0.0, float(self.jeu_m or 0.0))
        if not rect_dans_polygone(*rect_occupe(pl, jeu), self.capacity.points):
            return "déborde de la cale" + mention_debord(pl, jeu=jeu)
        obstacle = self.hold().rect_sur_obstacle(rect_occupe(pl, jeu))
        if obstacle is not None:
            return _motif_obstacle(obstacle) + mention_debord(pl, jeu=jeu)
        for q in self.placements:
            if q is not pl and se_touchent(pl, q, jeu):
                return f"chevauche « {q.nom} »" + mention_debord(pl, q, jeu=jeu)
        return None

    def appliquer(self, pl, **modifs):
        """Change la pose et l'annule si elle devient invalide. Retourne la
        raison du refus, ou None. Toutes les manipulations passent par là :
        aucune ne peut faire mordre deux charges l'une sur l'autre."""
        if "rot" in modifs and modifs["rot"] != pl.rot \
                and not getattr(pl, "rotation_permise", True):
            refus = "rotation interdite pour ce type"
            self.refuse.emit(f"{pl.nom} : {refus} — pose annulée.")
            return refus
        avant = {k: getattr(pl, k) for k in modifs}
        for k, v in modifs.items():
            setattr(pl, k, v)
        # lâché juste sur une pile du même lot : on empile (même règle que
        # le plan de pont), sinon on refuse en disant pourquoi
        pile = self.pile_sous(pl) if ("x" in modifs or "y" in modifs) else None
        if pile is not None:
            refus = gerbage_refuse(pile, max(1, pl.niveaux))
            for k, v in avant.items():
                setattr(pl, k, v)
            if refus is None:
                self.placements.remove(pl)
                pile.niveaux = max(1, pile.niveaux) + max(1, pl.niveaux)
                self.selected = pile
                self.selection_changed.emit(pile)
                return None
            self.refuse.emit(f"{pl.nom} : {refus} — pose annulée.")
            return refus
        refus = self.pose_refusee(pl)
        if refus is not None:
            for k, v in avant.items():
                setattr(pl, k, v)
            self.refuse.emit(f"{pl.nom} : {refus} — pose annulée.")
        return refus

    def pile_sous(self, pl):
        """La pile du même lot sur laquelle `pl` vient d'être lâché (même
        emprise, centre dedans), ou None."""
        cx, cy = pl.centre
        dx, dy = pl.emprise
        for q in self.placements:
            if q is pl or not meme_pile(q, pl):
                continue
            qx0, qy0, qx1, qy1 = q.rect
            ex, ey = q.emprise
            if (abs(ex - dx) < 1e-6 and abs(ey - dy) < 1e-6
                    and qx0 < cx < qx1 and qy0 < cy < qy1):
                return q
        return None

    def raisons(self, p, hold=None):
        """Tout ce qui ne va pas pour ce colis : ce qui aurait dû empêcher la
        pose, et les deux calques non bloquants (hauteur libre, charge)."""
        hold = hold or self.hold()
        out = []
        refus = self.pose_refusee(p)
        if refus is not None:
            out.append(refus)
        # marchandise dangereuse hors d'une cale qui admet sa classe (D-83) :
        # le même motif que sur le plan du pont
        classe = str(getattr(p, "classe_imdg", "") or "")
        if classe and not hold.admet_imdg(classe):
            admises = ", ".join(hold.classes_imdg) if hold.classes_imdg else "aucune"
            out.append(f"marchandise dangereuse classe IMDG {classe} : cette cale "
                       f"ne l'admet pas (classes admises : {admises})")
        haut = trop_haut(hold, p)
        if haut is not None:
            out.append(haut)
        lim = hold.charge_admissible_en(p.rect)
        if lim > 0 and p.charge_surfacique_t_m2() > lim + 1e-9:
            out.append(f"{p.charge_surfacique_t_m2():.2f} t/m² > "
                       f"{lim:.2f} admissible ici")
        return out

    def problemes(self):
        """[(placement, raison)] pour tout ce qui ne va pas."""
        hold = self.hold()
        return [(p, why) for p in self.placements for why in self.raisons(p, hold)]

    def infobulle(self, pl):
        dx, dy = pl.emprise
        libre = self.hold().hauteur_libre_en(pl.rect)
        lignes = [f"<b>{pl.nom}</b> — {dx:g} × {dy:g} m, "
                  f"{pl.hauteur_totale_m:.2f} m de haut, {pl.poids_total_t:.2f} t"
                  + (f" · pile de {pl.niveaux}" if pl.niveaux > 1 else ""),
                  f"hauteur libre ici {libre:.2f} m"]
        if pl.deborde:
            ex, ey = pl.encombrement
            lignes.insert(1, f"débord {pl.debord_m:g} m — encombrement "
                             f"{ex:g} × {ey:g} m")
        lignes += [f"<span style='color:{theme.DANGER}'>{why}</span>"
                   for why in self.raisons(pl)]
        return "<br>".join(lignes)

    def event(self, event):
        if event.type() == QEvent.Type.ToolTip:
            geom = self._geom()
            pl = None
            if geom is not None:
                x, y = self.to_ship(event.pos().x(), event.pos().y(), geom)
                pl = self._at(x, y)
            if pl is None:
                QToolTip.hideText()
            else:
                QToolTip.showText(event.globalPos(), self.infobulle(pl), self)
            return True
        return super().event(event)

    def hold(self):
        """La cale vue par le moteur : contour, hauteur, charge — et tout ce
        qui interdit la pose, structure permanente ET épontilles en place."""
        c = self.capacity
        return Hold(c.code, list(c.points), c.z_min, c.z_max,
                    getattr(c, "charge_admissible_t_m2", 0.0), c.name,
                    obstacles=[tuple(o)
                               for o in _obstacles_actifs(
                                   c, self.epontilles_en_place)],
                    zones_charge=list(getattr(c, "zones_charge", [])),
                    classes_imdg=list(getattr(c, "classes_imdg", []) or []))

    # ------------------------------------------------------------- dessin
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.BG_DEEP))
        geom = self._geom()
        if geom is None:
            p.setPen(QColor(theme.TEXT_FAINT))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Cette cale n'a pas de polygone tracé.")
            p.end()
            return

        if self._image is not None:
            m = self.capacity.plan.calibration.M
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
            p.setOpacity(0.65)
            p.drawImage(0, 0, self._image)
            p.restore()

        poly = QPolygonF([QPointF(*self.to_px(x, y, geom))
                          for x, y in self.capacity.points])
        p.setPen(QPen(QColor(theme.CAP_EDGE), 1.8))
        p.setBrush(QColor(theme.CAP_BASE) if self._image is None
                   else Qt.BrushStyle.NoBrush)
        p.drawPolygon(poly)

        _dessiner_zones_charge(p, getattr(self.capacity, "zones_charge", []),
                               lambda x, y: self.to_px(x, y, geom),
                               getattr(self.capacity, "charge_admissible_t_m2", 0.0))
        _dessiner_obstacles(p, getattr(self.capacity, "obstacles", []),
                            lambda x, y: self.to_px(x, y, geom))
        _dessiner_epontilles(p, self.capacity, self.epontilles_en_place,
                             lambda x, y: self.to_px(x, y, geom))

        mauvais = {id(pl) for pl, _ in self.problemes()}
        f = QFont()
        f.setPointSize(8)
        p.setFont(f)
        for pl in self.placements:
            x0, y0, x1, y1 = pl.rect
            ax, ay = self.to_px(x0, y1, geom)      # coin haut-gauche à l'écran
            bx, by = self.to_px(x1, y0, geom)
            rect = QRectF(ax, ay, bx - ax, by - ay)
            col = _couleur(pl)
            faute = id(pl) in mauvais
            p.setBrush(QColor(col.red(), col.green(), col.blue(),
                              200 if pl.niveaux > 1 else 150))
            if faute:
                p.setPen(QPen(QColor(theme.DANGER), 2.4))
            elif pl is self.selected:
                p.setPen(QPen(QColor(theme.CAP_SEL), 2.4))
            else:
                p.setPen(QPen(QColor(theme.SURFACE), 1.0))
            p.drawRect(rect)
            # ce qui dépasse de la palette se voit, en pointillé (D-39)
            if pl.deborde:
                ex0, ey0, ex1, ey1 = pl.rect_encombrement
                cx, cy = self.to_px(ex0, ey1, geom)
                dxp, dyp = self.to_px(ex1, ey0, geom)
                fin = QPen(QColor(col.red(), col.green(), col.blue(), 210), 1.0)
                fin.setStyle(Qt.PenStyle.DotLine)
                p.setPen(fin)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(QRectF(cx, cy, dxp - cx, dyp - cy))
            if pl.epingle:
                p.setPen(QPen(QColor(theme.SURFACE), 2.0))
                cx, cy = rect.center().x(), rect.top() + 6
                p.drawLine(int(cx - 3), int(cy), int(cx + 3), int(cy))
                p.drawLine(int(cx), int(cy - 3), int(cx), int(cy + 3))
            _etiquette_pile(p, rect, pl)
        p.end()

    # ------------------------------------------------------------- souris
    def _at(self, x, y):
        for pl in reversed(self.placements):
            x0, y0, x1, y1 = pl.rect
            if x0 <= x <= x1 and y0 <= y <= y1:
                return pl
        return None

    def mousePressEvent(self, event):
        geom = self._geom()
        if geom is None:
            return
        x, y = self.to_ship(event.position().x(), event.position().y(), geom)
        pl = self._at(x, y)
        self.selected = pl
        self.selection_changed.emit(pl)
        if pl is not None and event.button() == Qt.MouseButton.LeftButton \
                and not pl.epingle:
            # la pose de départ, pour y revenir si le lâcher est refusé
            self._drag = (pl, x - pl.x, y - pl.y, (pl.x, pl.y))
        self.update()

    def mouseMoveEvent(self, event):
        if self._drag is None:
            return
        pl, dx, dy, depart = self._drag
        # glissement interrompu (bouton relâché hors de la vue, autre bouton) :
        # la charge revient d'où elle vient, on ne la laisse pas en l'air
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            pl.x, pl.y = depart
            self._drag = None
            self.update()
            return
        geom = self._geom()
        if geom is None:
            return
        x, y = self.to_ship(event.position().x(), event.position().y(), geom)
        nx, ny = x - dx, y - dy
        if not (event.modifiers() & Qt.KeyboardModifier.AltModifier):
            nx = round(nx / PAS_SNAP) * PAS_SNAP
            ny = round(ny / PAS_SNAP) * PAS_SNAP
            nx, ny = self._aimanter(pl, nx, ny)
        pl.x, pl.y = nx, ny
        self.update()

    def _aimanter(self, pl, nx, ny):
        """Colle la charge à ses voisines et aux parois de la cale."""
        if not self.aimantation:
            return nx, ny
        # on aimante les PLACES OCCUPÉES : c'est ce qui se touche vraiment
        # quand les sacs dépassent de la palette (D-39) et quand on s'est
        # réservé un jeu d'arrimage (D-64). `aimanter` reçoit donc un jeu
        # NUL : il est déjà dans les rectangles.
        jeu = max(0.0, float(self.jeu_m or 0.0))
        d = max(0.0, pl.debord_m) + jeu
        dx, dy = pl.encombrement
        dx, dy = dx + 2 * jeu, dy + 2 * jeu
        voisins = [rect_occupe(q, jeu) for q in self.placements if q is not pl]
        # `hold()` fait déjà le tri que fait le contrôle de pose : seules les
        # zones SANS hauteur libre et les épontilles en place sont des murs
        # (D-30) ; une zone à hauteur réduite reste un calque (D-21) et
        # n'empêche pas de s'aimanter dessus.
        ax, ay = aimanter((nx - d, ny - d, nx - d + dx, ny - d + dy), voisins,
                          bornes_polygone(self.capacity.points), 0.0,
                          contour=self.capacity.points,
                          interdits=self.hold().zones_interdites)
        return ax + d, ay + d

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._drag is not None:
            pl, _dx, _dy, depart = self._drag
            self._drag = None
            # le glissement n'était qu'un aperçu : on repart de la pose de
            # départ et on demande le changement, refusable
            arrivee = (pl.x, pl.y)
            pl.x, pl.y = depart
            self.appliquer(pl, x=arrivee[0], y=arrivee[1])
            self.changed.emit()
            self.update()

    # ------------------------------------------------------------- clavier
    def keyPressEvent(self, event):
        pl = self.selected
        if pl is None:
            return super().keyPressEvent(event)
        k = event.key()
        if k in (Qt.Key.Key_R,):
            self.rotate_selected()
        elif k in (Qt.Key.Key_P,):
            pl.epingle = not pl.epingle
            self.changed.emit()
            self.update()
        elif k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.remove_selected()
        else:
            return super().keyPressEvent(event)

    # ------------------------------------------------------------- actions
    def rotate_selected(self):
        pl = self.selected
        if pl is None or pl.epingle:
            return
        # tourner peut faire mordre la voisine : même règle que déplacer. Le
        # colis pivote autour de son CENTRE (`pivot_en_place`), comme sur le
        # plan de pont : un colis posé se tourne là où il est.
        x, y, rot = pivot_en_place(pl)
        self.appliquer(pl, x=x, y=y, rot=rot)
        self.changed.emit()
        self.update()

    def remove_selected(self):
        pl = self.selected
        if pl is None:
            return
        if pl in self.placements:
            self.placements.remove(pl)
        self.selected = None
        self.selection_changed.emit(None)
        self.changed.emit()
        self.update()

    def add_placement(self, pl):
        """Pose une charge à la première place libre ; retourne True si posée."""
        hold = self.hold()
        packer = Packer(hold, self.placements, PAS_SNAP)

        # On cherche une place pour l'ENCOMBREMENT (débord compris) : ce que le
        # calepineur rend est donc le coin de l'encombrement, ramené au coin de
        # la palette par le débord juste avant de poser (D-39).
        d = max(0.0, pl.debord_m)

        def convient(x, y):
            # une place libre sous un barrot bas n'en est pas une pour un
            # colis plus haut que lui : on cherche plus loin d'abord
            pl.x, pl.y = x + d, y + d
            return trop_haut(hold, pl) is None

        pos = packer.place(pl.encombrement, convient)
        if pos is None and pl.rot == 0 and getattr(pl, "rotation_permise", True):
            pl.rot = 90
            pos = packer.place(pl.encombrement, convient)
        if pos is None:
            return False
        pl.x, pl.y = pos[0] + d, pos[1] + d
        self.placements.append(pl)
        self.selected = pl
        self.selection_changed.emit(pl)
        self.changed.emit()
        self.update()
        return True


class TypeDialog(QDialog):
    """Créer ou modifier un type de charge du catalogue."""

    def __init__(self, t: CargoType | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Type de charge")
        t = t or CargoType()
        self._origine = t          # ce que le formulaire ne montre pas s'y garde
        lay = QVBoxLayout(self)
        form = QFormLayout()
        from PySide6.QtWidgets import QLineEdit
        self.code = QLineEdit(t.code)
        self.nom = QLineEdit(t.nom)
        self.cat = QComboBox()
        self.cat.addItems(CATEGORIES)
        self.cat.setCurrentText(t.categorie if t.categorie in CATEGORIES
                                else CATEGORIES[0])
        self.l = SpinNombre(); self.l.setRange(0.05, 40); self.l.setDecimals(2)
        self.w = SpinNombre(); self.w.setRange(0.05, 40); self.w.setDecimals(2)
        # hauteur facultative au catalogue (0 = non renseignée) : elle se
        # précise au manifeste, lot par lot (D-36)
        self.h = SpinNombre(); self.h.setRange(0.0, 20); self.h.setDecimals(2)
        self.h.setSpecialValueText("non renseignée")
        self.p = SpinNombre(); self.p.setRange(0.001, 500); self.p.setDecimals(3)
        for sp, v in ((self.l, t.longueur_m), (self.w, t.largeur_m),
                      (self.h, t.hauteur_m)):
            sp.setSuffix(" m"); sp.setValue(v)
        self.p.setSuffix(" t"); self.p.setValue(t.poids_t)
        self.pmax = SpinNombre(); self.pmax.setRange(0.0, 500); self.pmax.setDecimals(3)
        self.pmax.setSuffix(" t"); self.pmax.setSpecialValueText("sans limite")
        self.pmax.setValue(t.poids_max_t)
        self.pmax.setToolTip("Au-delà de ce poids unitaire, la saisie est refusée.")
        self.gerbe = QSpinBox(); self.gerbe.setRange(1, 20)
        self.gerbe.setValue(max(1, t.gerbable_max))
        self.rot = QCheckBox("Rotation permise")
        self.rot.setChecked(t.rotation_permise)
        # couleur des colis de ce type sur le plan : vide = celle de la
        # catégorie. Un lot du manifeste peut toujours la remplacer.
        self._couleur = t.couleur
        self.b_coul = QPushButton()
        self.b_coul.setProperty("ghost", "1")
        self.b_coul.clicked.connect(self._choisir_couleur)
        self.b_coul_auto = QPushButton("Auto")
        self.b_coul_auto.setProperty("ghost", "1")
        self.b_coul_auto.setToolTip("Reprendre la couleur de la catégorie.")
        self.b_coul_auto.clicked.connect(lambda: self._poser_couleur(""))
        self._poser_couleur(t.couleur)
        coul = QHBoxLayout()
        coul.addWidget(self.b_coul, 1)
        coul.addWidget(self.b_coul_auto)
        self.note = QLineEdit(t.note)
        self.note.setPlaceholderText("Arrimage, provenance, remarque…")
        form.addRow("Code", self.code)
        form.addRow("Nom", self.nom)
        form.addRow("Catégorie", self.cat)
        form.addRow("Longueur (X)", self.l)
        form.addRow("Largeur (Y)", self.w)
        form.addRow("Hauteur", self.h)
        form.addRow("Poids", self.p)
        form.addRow("Poids maximal", self.pmax)
        form.addRow("Stack (couches)", self.gerbe)
        form.addRow("", self.rot)
        form.addRow("Couleur", coul)
        form.addRow("Note", self.note)
        lay.addLayout(form)
        row = QHBoxLayout()
        row.addStretch(1)
        b_ko = QPushButton("Annuler"); b_ko.clicked.connect(self.reject)
        b_ok = QPushButton("Valider"); b_ok.setProperty("accent", "1")
        b_ok.clicked.connect(self.accept)
        row.addWidget(b_ko); row.addWidget(b_ok)
        lay.addLayout(row)

    def _poser_couleur(self, hexa):
        from .core.cargo_model import COULEURS_CATEGORIE
        self._couleur = hexa or ""
        vue = hexa or COULEURS_CATEGORIE.get(self.cat.currentText(),
                                             COULEURS_CATEGORIE["Autre"])
        self.b_coul.setText(hexa or "selon la catégorie")
        self.b_coul.setStyleSheet(
            f"QPushButton {{ border-left: 14px solid {vue}; padding-left: 8px; }}")

    def _choisir_couleur(self):
        from PySide6.QtWidgets import QColorDialog
        from PySide6.QtGui import QColor
        c = QColorDialog.getColor(QColor(self._couleur or "#888888"), self,
                                  "Couleur des colis de ce type")
        if c.isValid():
            self._poser_couleur(c.name())

    def values(self) -> CargoType:
        # la source n'est pas au formulaire : on la reporte du type d'origine,
        # sinon modifier un type l'effaçait
        o = self._origine
        return CargoType(
            code=(self.code.text().strip().upper() or "TYPE"),
            nom=self.nom.text().strip() or self.code.text().strip(),
            categorie=self.cat.currentText(),
            longueur_m=self.l.value(), largeur_m=self.w.value(),
            hauteur_m=self.h.value(), poids_t=self.p.value(),
            poids_max_t=self.pmax.value(),
            gerbable_max=self.gerbe.value(),
            rotation_permise=self.rot.isChecked(),
            couleur=self._couleur, note=self.note.text().strip(),
            source=o.source)


class ObstaclesDialog(QDialog):
    """Les zones où rien ne peut être posé dans cette cale.

    Épontilles, descentes, puits, échelles : une cale n'est pas forcément
    entièrement utilisable, même quand son polygone l'est. Chaque zone est un
    rectangle en repère navire ; le solveur les contourne, la pose à la main
    les refuse, et elles sont hachurées sur tous les plans."""

    def __init__(self, capacity, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Zones interdites — {capacity.code}")
        self.resize(560, 420)
        from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem
        self._QTableWidgetItem = QTableWidgetItem

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)
        intro = QLabel(
            "Rectangles en repère navire : X/Y du coin bas-gauche (X mini, "
            "Y mini) et dimensions. Ces zones appartiennent au navire — elles "
            "valent pour tous les chargements et sont enregistrées avec les "
            "plans.<br>Une zone dont le nom porte une hauteur (« hauteur libre "
            "1.70 m ») n'interdit rien : c'est un calque, comme les charges "
            "admissibles — on y pose, et une pile plus haute y est signalée "
            "en rouge. Sans hauteur, rien ne s'y pose.")
        intro.setObjectName("hint")
        intro.setWordWrap(True)
        root.addWidget(intro)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Nom", "X (m)", "Y (m)", "Long. X (m)", "Larg. Y (m)"])
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 5):
            head.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        root.addWidget(self.table, 1)
        for o in getattr(capacity, "obstacles", []) or []:
            if len(o) >= 4:
                x0, y0, x1, y1 = (float(v) for v in o[:4])
                nom = str(o[4]) if len(o) > 4 else ""
                self._ajouter_ligne(nom, min(x0, x1), min(y0, y1),
                                    abs(x1 - x0), abs(y1 - y0))

        row = QHBoxLayout()
        b_add = QPushButton("+ Zone")
        b_add.setProperty("ghost", "1")
        b_add.clicked.connect(lambda: self._ajouter_ligne("Épontille",
                                                          0.0, 0.0, 0.3, 0.3))
        b_del = QPushButton("Supprimer")
        b_del.setProperty("ghost", "1")
        b_del.clicked.connect(self._supprimer)
        row.addWidget(b_add)
        row.addWidget(b_del)
        row.addStretch(1)
        b_ko = QPushButton("Annuler")
        b_ko.clicked.connect(self.reject)
        b_ok = QPushButton("Valider")
        b_ok.setProperty("accent", "1")
        b_ok.clicked.connect(self.accept)
        row.addWidget(b_ko)
        row.addWidget(b_ok)
        root.addLayout(row)

    def _ajouter_ligne(self, nom, x, y, lx, ly):
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, v in enumerate([nom, f"{x:g}", f"{y:g}", f"{lx:g}", f"{ly:g}"]):
            self.table.setItem(r, c, self._QTableWidgetItem(v))

    def _supprimer(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()},
                      reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def values(self):
        out = []
        for r in range(self.table.rowCount()):
            try:
                nom = self.table.item(r, 0).text().strip()
                x = float(self.table.item(r, 1).text().replace(",", "."))
                y = float(self.table.item(r, 2).text().replace(",", "."))
                lx = float(self.table.item(r, 3).text().replace(",", "."))
                ly = float(self.table.item(r, 4).text().replace(",", "."))
            except (AttributeError, ValueError):
                continue
            if lx > 0 and ly > 0:
                out.append([x, y, x + lx, y + ly, nom])
        return out


class StowEditorDialog(QDialog):
    """Plan de chargement d'une cale."""

    def __init__(self, win, capacity, condition, catalogue, parent=None):
        pere = parent if isinstance(parent, QWidget) else (
            win if isinstance(win, QWidget) else None)
        super().__init__(pere)
        self.win = win
        self.capacity = capacity
        self.condition = condition
        self.catalogue = catalogue
        self.setWindowTitle(f"Plan de chargement — {capacity.code}")
        self.resize(1240, 760)

        self.placements = [Placement.from_dict(p.to_dict())
                           for p in condition.placements.get(capacity.code, [])]

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)

        left = QVBoxLayout()
        hdr = QLabel(f"{capacity.code} — {capacity.name or 'sans nom'}")
        hdr.setStyleSheet("font-size: 15px; font-weight: bold;")
        left.addWidget(hdr)
        hint = QLabel("Glisser pour déplacer · R : tourner · P : épingler · "
                      "Suppr : retirer · Alt : ni magnétisme ni aimantation")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        left.addWidget(hint)

        barre = QHBoxLayout()
        barre.setSpacing(8)
        self.chk_aimant = QCheckBox("Aimanter les colis entre eux")
        self.chk_aimant.setChecked(True)
        self.chk_aimant.setToolTip(
            "Coller bord à bord au voisin et à la paroi, et aligner les "
            "rangées, dès qu'on passe à moins de 20 cm.")
        self.chk_aimant.toggled.connect(self._on_aimant)
        barre.addWidget(self.chk_aimant)
        barre.addWidget(QLabel("jeu d'arrimage"))
        self.sp_jeu = SpinNombre()
        self.sp_jeu.setRange(0.0, 1.0)
        self.sp_jeu.setSingleStep(0.05)
        self.sp_jeu.setDecimals(2)
        self.sp_jeu.setSuffix(" m")
        self.sp_jeu.setToolTip(
            "Le DÉBORDEMENT qu'on prête à chaque colis, de chaque côté : une "
            "palette affaissée dont le contenu dépasse, la place des saisines, "
            "le passage des fourches. Deux voisins sont donc écartés de deux "
            "fois cette valeur, un colis et la muraille d'une seule. Il "
            "s'applique à la main comme au calepinage de « Remplir depuis le "
            "manifeste », et une pose qui ne le respecte pas est refusée. En "
            "deçà de 2 cm, le calepinage garde sa marge : deux emprises ne se "
            "touchent jamais exactement.\n\nÀ ne pas confondre avec le DÉBORD, "
            "qui est une dimension du LOT — ce qui dépasse vraiment de la "
            "palette — et se règle au manifeste. Les deux s'additionnent.")
        self.sp_jeu.valueChanged.connect(self._on_jeu)
        barre.addWidget(self.sp_jeu)
        barre.addStretch(1)
        left.addLayout(barre)
        self.canvas = StowCanvas(capacity, self.placements)
        # les épontilles en place viennent du POINT : ce plan de cale en tient
        # compte exactement comme le plan de pont (elles s'y posent depuis la
        # vue Chargement, pas ici — un plan de cale ne modifie pas le navire)
        self.canvas.epontilles_en_place = set(
            getattr(condition, "epontilles_en_place", []) or [])
        self.canvas.changed.connect(self.refresh)
        self.canvas.selection_changed.connect(self.on_selection)
        self.canvas.refuse.connect(self._refus)
        left.addWidget(self.canvas, 1)
        self.lbl_probs = QLabel("")
        self.lbl_probs.setWordWrap(True)
        left.addWidget(self.lbl_probs)
        root.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(10)

        # On pose ce qu'il y a À EMBARQUER, pas n'importe quel type du
        # catalogue : le catalogue dit ce que le navire sait porter, le
        # manifeste dit ce qui attend sur le quai. C'est le second qu'on sert.
        frame, lay = _card("À embarquer")
        self.list_types = QListWidget()
        self.list_types.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.list_types.setMaximumHeight(170)
        self.list_types.itemDoubleClicked.connect(lambda _: self.add_selected_type())
        lay.addWidget(self.list_types)
        b_add = QPushButton("Poser dans la cale")
        b_add.setProperty("accent", "1")
        b_add.clicked.connect(self.add_selected_type)
        lay.addWidget(b_add)
        self.lbl_lots = QLabel("")
        self.lbl_lots.setObjectName("hint")
        self.lbl_lots.setWordWrap(True)
        lay.addWidget(self.lbl_lots)
        b_one = QPushButton("Charge ponctuelle (hors manifeste)…")
        b_one.setProperty("ghost", "1")
        b_one.clicked.connect(self.add_one_shot)
        lay.addWidget(b_one)
        right.addWidget(frame)

        frame, lay = _card("Charge sélectionnée")
        form = QFormLayout()
        self.sp_niv = QSpinBox(); self.sp_niv.setRange(1, 20)
        self.sp_niv.valueChanged.connect(self.on_niveaux)
        self.chk_pin = QCheckBox("Épinglée (le solveur ne la déplace pas)")
        self.chk_pin.stateChanged.connect(self.on_pin)
        form.addRow("Couches empilées", self.sp_niv)
        self.lbl_sel = QLabel("Aucune charge sélectionnée.")
        self.lbl_sel.setObjectName("hint")
        self.lbl_sel.setWordWrap(True)
        lay.addWidget(self.lbl_sel)
        lay.addLayout(form)
        lay.addWidget(self.chk_pin)
        row = QHBoxLayout()
        b_rot = QPushButton("Tourner")
        b_rot.setProperty("ghost", "1")
        b_rot.clicked.connect(self.canvas.rotate_selected)
        b_del = QPushButton("Retirer")
        b_del.setProperty("ghost", "1")
        b_del.clicked.connect(self.canvas.remove_selected)
        row.addWidget(b_rot, 1); row.addWidget(b_del, 1)
        lay.addLayout(row)
        right.addWidget(frame)

        frame, lay = _card("Cale")
        self.lbl_cale = QLabel("")
        self.lbl_cale.setWordWrap(True)
        lay.addWidget(self.lbl_cale)
        b_fill = QPushButton("Remplir depuis le manifeste")
        b_fill.setProperty("ghost", "1")
        b_fill.clicked.connect(self.fill_from_manifest)
        # Sous le bouton, les réglages employés : le remplissage automatique
        # est celui du répartiteur, et le bord doit pouvoir le vérifier d'un
        # coup d'œil plutôt que de comparer deux plans.
        self.lbl_reglages = QLabel("")
        self.lbl_reglages.setObjectName("hint")
        self.lbl_reglages.setWordWrap(True)
        b_clear = QPushButton("Vider la cale")
        b_clear.setProperty("ghost", "1")
        b_clear.clicked.connect(self.clear_all)
        b_obs = QPushButton("Zones interdites…")
        b_obs.setProperty("ghost", "1")
        b_obs.setToolTip("Épontilles, descentes, puits… : les surfaces de la "
                         "cale où rien ne peut être posé — et les zones de "
                         "hauteur réduite (« hauteur libre 1.70 m »), qui "
                         "n'interdisent rien mais signalent une pile trop "
                         "haute. Elles appartiennent au navire et valent pour "
                         "tous les chargements.")
        b_obs.clicked.connect(self.edit_obstacles)
        b_fond = QPushButton("Fond de plan…")
        b_fond.setProperty("ghost", "1")
        b_fond.setToolTip(
            "La vue de dessus de CETTE cale (DXF, PDF ou image), calée dans "
            "le repère du navire : elle se dessine sous les colis. Sans elle, "
            "on place les palettes sur un fond neutre — le contour est juste, "
            "mais on ne voit ni les descentes ni les épontilles du dessin.")
        b_fond.clicked.connect(self.edit_fond_de_plan)
        lay.addWidget(b_fill)
        lay.addWidget(self.lbl_reglages)
        lay.addWidget(b_clear)
        lay.addWidget(b_obs)
        lay.addWidget(b_fond)
        right.addWidget(frame)

        frame, lay = _card("Totaux")
        self.lbl_totaux = QLabel("—")
        self.lbl_totaux.setWordWrap(True)
        self.lbl_totaux.setStyleSheet("font-weight: bold;")
        lay.addWidget(self.lbl_totaux)
        right.addWidget(frame)
        right.addStretch(1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        b_cancel = QPushButton("Annuler")
        b_cancel.clicked.connect(self.reject)
        b_ok = QPushButton("Appliquer")
        b_ok.setProperty("accent", "1")
        b_ok.clicked.connect(self.accept)
        btns.addWidget(b_cancel); btns.addWidget(b_ok)
        left.addLayout(btns)

        inner = QWidget()
        inner.setLayout(right)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        scroll.setFixedWidth(348)
        root.addWidget(scroll)

        # La molette reprend le jeu d'arrimage réglé à la vue Chargement,
        # pas un zéro : le même moteur doit poser la même chose des deux
        # côtés, et le bord n'a pas à retaper son réglage ici (D-39). Ici et
        # pas plus haut : la poser déclenche `_on_jeu`, qui écrit sous le
        # bouton « Remplir » — l'étiquette doit exister.
        from .cargo_panel import jeu_arrimage
        self.sp_jeu.setValue(jeu_arrimage(win))
        self.reload_types()
        self._dire_reglages()
        self.refresh()

    # ------------------------------------------------- réglages du remplissage
    def reglages_remplissage(self):
        """Les réglages du prochain « Remplir » : ceux du répartiteur, plus le
        jeu réglé ici."""
        return reglages_du_remplissage(self.win, self.canvas.jeu_m)

    def _dire_reglages(self):
        """Affiche sous le bouton avec quoi la cale sera (ou a été) remplie."""
        du_solveur = isinstance(
            getattr(self.win, "derniers_reglages_solveur", None), Reglages)
        self.lbl_reglages.setText(
            dire_reglages(self.reglages_remplissage(), du_solveur))

    # ------------------------------------------------------------- catalogue
    def _places_par_ligne(self):
        """Le compte du manifeste tel qu'il sera une fois la boîte appliquée.

        On travaille sur des copies : la condition, elle, garde l'ancien plan
        de cette cale jusqu'à « Appliquer ». Compter dessus, c'est ne jamais
        voir le reste baisser — et poser au-delà du manifeste."""
        import copy
        cond = copy.copy(self.condition)
        cond.placements = {**self.condition.placements,
                           self.capacity.code: self.placements}
        return cond.places_par_ligne()

    def reload_types(self):
        """Les lots du manifeste, avec ce qu'il en reste à embarquer."""
        from .manifest_panel import _pastille
        from .core.cargo_model import couleur_hex
        courant = self.selected_lot()
        self.list_types.clear()
        cond = self.condition
        restes = self._places_par_ligne()
        for i, m in enumerate(cond.manifeste):
            reste = ("du bord" if m.hors_manifeste
                     else f"reste {max(0, m.quantite - restes[i])}")
            item = QListWidgetItem(
                f"{m.nom}  ({m.longueur_m:g}×{m.largeur_m:g} m, {m.poids_t:g} t) — {reste}")
            item.setIcon(_pastille(couleur_hex(m)))
            item.setData(Qt.ItemDataRole.UserRole, m.lot_id)
            self.list_types.addItem(item)
        if not cond.manifeste:
            self.lbl_lots.setText(
                "Le manifeste est vide : composez-le d'abord (bouton "
                "« Manifeste… » de la vue Chargement), ou posez une charge "
                "ponctuelle ci-dessous.")
        else:
            self.lbl_lots.setText(
                "Un lot épuisé ne se pose plus : augmentez sa quantité au "
                "manifeste. Les charges du bord, elles, n'ont pas de reste.")
        if self.list_types.count():
            index = next((i for i, m in enumerate(cond.manifeste)
                          if courant is not None and m.lot_id == courant.lot_id), 0)
            self.list_types.setCurrentRow(index)

    def selected_lot(self):
        item = self.list_types.currentItem()
        if item is None:
            return None
        lot_id = item.data(Qt.ItemDataRole.UserRole)
        return next((m for m in self.condition.manifeste if m.lot_id == lot_id), None)

    def selected_type(self):
        """Le type du catalogue derrière le lot choisi (compatibilité)."""
        m = self.selected_lot()
        if m is None or not m.type_code:
            return None
        return self.catalogue.get(m.type_code) if self.catalogue else None

    def new_type(self):
        dlg = TypeDialog(parent=self)
        if dlg.exec():
            t = dlg.values()
            t.code = self.catalogue.unique_code(t.code)
            self.catalogue.add(t)
            self.reload_types()

    def edit_type(self):
        t = self.selected_type()
        if t is None:
            return
        dlg = TypeDialog(t, parent=self)
        if dlg.exec():
            nouveau = dlg.values()
            nouveau.code = t.code       # le code identifie le type : il ne bouge pas
            self.catalogue.add(nouveau)
            self.reload_types()

    def add_selected_type(self):
        m = self.selected_lot()
        if m is None:
            return
        if not m.hors_manifeste:
            i = self.condition.manifeste.index(m)
            reste = m.quantite - self._places_par_ligne()[i]
            if reste <= 0:
                QMessageBox.information(
                    self, "Lot épuisé",
                    f"« {m.nom} » : tout est posé ({m.quantite} sur {m.quantite}).\n\n"
                    "Augmentez la quantité au manifeste pour en poser davantage.")
                return
        pl = m.to_placement()
        pl.niveaux = 1
        if not self.canvas.add_placement(pl):
            QMessageBox.information(
                self, "Poser une charge",
                "Aucune place libre pour cette charge dans la cale.")
        self.reload_types()

    def add_one_shot(self):
        dlg = TypeDialog(parent=self)
        dlg.setWindowTitle("Charge ponctuelle (hors manifeste)")
        dlg.code.setText("PONCTUEL")
        if not dlg.exec():
            return
        t = dlg.values()
        # une charge ponctuelle est posée tout de suite : sa hauteur ne peut
        # pas rester « non renseignée », elle entre dans le VCG (D-36)
        if not t.hauteur_renseignee:
            QMessageBox.information(
                self, "Charge ponctuelle",
                "Donnez la hauteur de cette charge : elle sert au contrôle de "
                "hauteur libre de la cale et au centre de gravité.")
            return
        pl = Placement.from_type(t)
        pl.type_code = ""            # ponctuelle : jamais rattachée au catalogue
        if not self.canvas.add_placement(pl):
            QMessageBox.information(self, "Charge ponctuelle",
                                    "Aucune place libre dans la cale.")

    # ------------------------------------------------------------- sélection
    def on_selection(self, pl):
        for w in (self.sp_niv, self.chk_pin):
            w.blockSignals(True)
        if pl is None:
            self.lbl_sel.setText("Aucune charge sélectionnée.")
            self.sp_niv.setValue(1)
            self.chk_pin.setChecked(False)
        else:
            hold = self.canvas.hold()
            # plafond commun : stack de la marchandise ET hauteur libre
            # à l'endroit de la pile (zones de hauteur réduite comprises)
            libre = hold.hauteur_libre_en(pl.rect)
            nmax = pl.niveaux_max(libre)
            self.sp_niv.setMaximum(nmax)
            self.sp_niv.setValue(max(1, min(pl.niveaux, nmax)))
            self.sp_niv.setToolTip(
                f"{nmax} couche(s) au plus : stack {pl.gerbable_max} et "
                f"{libre:.2f} m libres ici pour "
                f"{pl.hauteur_m:.2f} m par exemplaire.")
            self.chk_pin.setChecked(pl.epingle)
            dx, dy = pl.emprise
            self.lbl_sel.setText(
                f"{pl.nom} · {dx:g}×{dy:g} m · {pl.poids_total_t:.2f} t · "
                f"hauteur {pl.hauteur_totale_m:.2f} m (max {nmax} couche"
                f"{'s' if nmax > 1 else ''})\n"
                f"position X {pl.x:.2f} m, Y {pl.y:+.2f} m")
        for w in (self.sp_niv, self.chk_pin):
            w.blockSignals(False)

    def on_niveaux(self, v):
        pl = self.canvas.selected
        if pl is not None:
            pl.niveaux = v
            self.refresh()
            self.canvas.update()

    def on_pin(self, state):
        pl = self.canvas.selected
        if pl is not None:
            if pl.est_materiel_bord and not state:
                # un engin du bord reste épinglé : le solveur ne le déplace pas
                self.chk_pin.setChecked(True)
                return
            pl.epingle = bool(state)
            self.canvas.update()

    # ------------------------------------------------------------- cale
    def fill_from_manifest(self):
        """Remplit CETTE cale avec le manifeste, sans toucher aux épinglées.

        Le solveur ne reçoit que ce qu'il RESTE à poser : ce qui est déjà dans
        les autres cales, ce qu'on garde ici (épinglées, charges du bord)
        compte. Lui donner la quantité entière dépassait le manifeste.

        Les réglages sont ceux du DERNIER passage du répartiteur, le jeu de ce
        plan de cale en plus (`reglages_remplissage`) : c'est le même moteur,
        il doit poser la même chose."""
        from .core import stowage
        from .solver_dialog import lignes_restantes
        cond = self.condition
        lignes = [m for m in cond.lignes_a_embarquer() if m.quantite > 0]
        if not lignes:
            QMessageBox.information(
                self, "Remplir",
                "Le manifeste est vide : ajoutez ce qu'il y a à embarquer "
                "dans le panneau « Condition de chargement ».")
            return
        # les charges du bord ne se répartissent pas : elles restent posées
        lots_du_bord = {m.lot_id for m in cond.manifeste if m.hors_manifeste}
        # le matériel du bord ne se répartit jamais : il est gardé même si
        # quelqu'un a décoché son épingle (D-18)
        gardes = [p for p in self.placements
                  if p.epingle or p.est_materiel_bord
                  or (p.lot_id and p.lot_id in lots_du_bord)]
        code = self.capacity.code
        lignes = lignes_restantes(lignes, cond, {code: gardes}, {code})
        if not lignes:
            self._dire("Tout le manifeste est déjà posé : rien à ajouter "
                       "dans cette cale.")
            return
        # le reste du navire entre dans la cible de gîte comme dans celle
        # d'assiette : même moteur, mêmes cibles que le répartiteur (D-39)
        from .solver_dialog import hors_cargaison
        poids_hors, moment_hors, moment_t_hors = hors_cargaison(self.win, cond, {code})
        rap = stowage.resoudre([self.canvas.hold()], lignes,
                               self.reglages_remplissage(),
                               epingles={code: gardes},
                               navire=getattr(self.win, "nav", None),
                               poids_hors_cargaison_t=poids_hors,
                               moment_hors_cargaison_tm=moment_hors,
                               moment_t_hors_cargaison_tm=moment_t_hors)
        self.placements[:] = rap.places[code]
        self.canvas.placements = self.placements
        self.canvas.selected = None
        self._dire_reglages()
        self.refresh()
        self.canvas.update()
        reste = sum(q for _, q, _ in rap.non_places)
        self._dire(f"{rap.nb_places} charge(s) posée(s)"
                   + (f", {reste} sans place dans cette cale." if reste else "."))

    def _dire(self, message):
        barre = getattr(self.win, "statusBar", None)
        if callable(barre):
            barre().showMessage(message, 8000)

    def clear_all(self):
        garde = [p for p in self.placements if p.epingle or p.est_materiel_bord]
        self.placements[:] = garde
        self.canvas.placements = self.placements
        self.canvas.selected = None
        self.refresh()
        self.canvas.update()

    # ------------------------------------------------------------- état
    def refresh(self):
        hold = self.canvas.hold()
        w = sum(p.poids_total_t for p in self.placements)
        n = sum(max(1, p.niveaux) for p in self.placements)
        # « occupation » répond à « que reste-t-il de place ? » : on compte
        # donc l'encombrement, débord compris (D-39)
        emprise = sum(p.encombrement[0] * p.encombrement[1]
                      for p in self.placements)
        aire = hold.aire_m2
        if w > 0:
            lm = sum(p.poids_total_t * p.centre[0] for p in self.placements)
            tm = sum(p.poids_total_t * p.centre[1] for p in self.placements)
            vm = sum(p.poids_total_t * p.vcg(hold.z_min) for p in self.placements)
            self.lbl_totaux.setText(
                f"{n} charge(s) · {w:.2f} t\n"
                f"LCG {lm / w:.2f} m · TCG {tm / w:+.2f} m · VCG {vm / w:.2f} m")
        else:
            self.lbl_totaux.setText("Cale vide.")
        charge = (w / aire) if aire > 0 else 0.0
        lim = hold.charge_admissible_t_m2
        txt = (f"Hauteur utile {hold.hauteur_utile_m:.2f} m · "
               f"surface {aire:.0f} m² · occupation "
               f"{(100 * emprise / aire) if aire else 0:.0f} %\n"
               f"Charge moyenne {charge:.2f} t/m²")
        txt += (f" (admissible {lim:.2f})" if lim > 0
                else " (charge admissible non renseignée)")
        self.lbl_cale.setText(txt)

        probs = self.canvas.problemes()
        motif = getattr(self, "_motif_refus", "")
        self._motif_refus = ""
        if probs:
            lignes = [f"• {p.nom} : {why}" for p, why in probs[:6]]
            if len(probs) > 6:
                lignes.append(f"… et {len(probs) - 6} autre(s)")
            self.lbl_probs.setText(
                f"<b style='color:{theme.DANGER}'>{len(probs)} problème(s)</b><br>"
                + "<br>".join(lignes))
        elif motif:
            self.lbl_probs.setText(
                f"<b style='color:{theme.DANGER}'>{motif}</b>")
        else:
            self.lbl_probs.setText(
                f"<span style='color:{theme.OK}'>Plan valide : rien ne "
                "déborde ni ne se chevauche.</span>")

    def _on_aimant(self, actif):
        """« Aimanter » ne commande QUE l'aimantation.

        Le jeu d'arrimage reste réglable : il sert aussi au calepinage de
        « Remplir depuis le manifeste », qui continue de l'appliquer quand
        l'aimantation est décochée. Un champ éteint et des colis espacés quand
        même, c'est ce que le bord ne comprenait pas (même correction qu'à la
        vue Chargement)."""
        self.canvas.aimantation = bool(actif)

    def _on_jeu(self, v):
        self.canvas.jeu_m = float(v)
        # le jeu vaut pour l'aimantation ET pour le remplissage automatique :
        # ce qui est annoncé sous le bouton suit la molette
        self._dire_reglages()

    def edit_obstacles(self):
        """Zones interdites de la cale : elles appartiennent à la géométrie du
        navire (pas au chargement) et sont enregistrées immédiatement."""
        dlg = ObstaclesDialog(self.capacity, self)
        if dlg.exec():
            self.capacity.obstacles = dlg.values()
            # géométrie du navire : on écrit tout de suite, pour tous les cas
            from . import app_paths
            proj = getattr(self.win, "project", None)
            if proj is not None:
                try:
                    proj.save_geometry(app_paths.ship_folder())
                except OSError as e:
                    # une géométrie non enregistrée, c'est des zones perdues
                    # à la prochaine ouverture : on le dit
                    self._dire(f"Zones interdites non enregistrées : {e}")
                    QMessageBox.warning(
                        self, "Zones interdites",
                        "Les zones sont prises en compte pour ce chargement, "
                        f"mais n'ont pas pu être enregistrées avec le navire :\n{e}")
            self.refresh()
            self.canvas.update()

    def edit_fond_de_plan(self):
        """Le plan de cale dessiné derrière les colis (`capacity.plan`).

        Il appartient à la géométrie du navire, comme les zones interdites :
        on l'enregistre tout de suite, pour tous les chargements. Jusqu'ici la
        fiche existait (`cale_image.CaleImageDialog`) mais rien ne l'ouvrait
        dans l'application : le fond ne pouvait être posé qu'à la main dans
        `geometrie.json`."""
        from . import app_paths
        from .cale_image import CaleImageDialog
        dossier = app_paths.ship_folder()
        dlg = CaleImageDialog(self.capacity, self, ship_folder=dossier)
        if not dlg.exec():
            return dlg
        self.capacity.plan = dlg.values()
        self.canvas.reload_image()
        proj = getattr(self.win, "project", None)
        if proj is not None:
            try:
                proj.save_geometry(dossier)
            except OSError as e:
                # un fond non enregistré, c'est un calage à refaire à la
                # prochaine ouverture : on le dit plutôt que de le taire
                self._dire(f"Fond de plan non enregistré : {e}")
                QMessageBox.warning(
                    self, "Fond de plan",
                    "Le fond est en place pour ce chargement, mais n'a pas pu "
                    f"être enregistré avec le navire :\n{e}")
        self.refresh()
        return dlg

    def _refus(self, texte):
        """Une pose vient d'être annulée. On garde le motif pour l'affichage
        qui suit : sans lui, la charge semblerait revenir toute seule."""
        self._motif_refus = texte

    def values(self):
        return self.placements
