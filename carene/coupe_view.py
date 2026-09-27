# -*- coding: utf-8 -*-
"""La coupe transversale au repère — maquette C-A.

Au couple choisi sur le plan de pont (le trait rouge, qu'on glisse), on voit
le navire en travers : les ponts à leur hauteur, la largeur de chaque cale
à cet endroit, la hauteur libre, les charges qui traversent cette coupe avec
leur empilement, la flottaison du calcul en cours et la gîte.

La silhouette de coque est **schématique** : elle passe par la demi-largeur
des contours de pont tracés à ce couple, et se ferme sur la quille par un
tracé arbitraire. Elle situe, elle ne mesure rien (D-10).

Dès que le plan des formes est décalqué — `formes.json` dans le
dossier du navire — c'est **lui** qui donne la section, et le cartouche le
nomme au lieu de dire « schématique ». Rien d'autre ne change : les cales, les
charges, la flottaison et tous les chiffres restent ceux du calcul, qui repose
sur les tables du dossier approuvé.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from . import theme
from .core.stowage import Hold, hauteur_libre_de, trop_haut
from .profil_view import (
    dossier_du_navire,
    formes_du_bord,
    nom_du_trace,
    section_relevee,
)
from .project import KIND_CONTOUR


def _hauteur_libre(obstacle):
    """Hauteur libre annoncée par une zone, lue dans son nom (« hauteur libre
    1.70 m ») — la même lecture que le moteur (`stowage.hauteur_libre_de`).
    Rien de deviné : sans nombre, on ne dessine pas de hauteur."""
    return hauteur_libre_de(obstacle)


def _hold_de(cap, epontilles_en_place=()):
    """La cale vue par le moteur, épontilles EN PLACE comprises : la coupe
    doit montrer le navire tel qu'il est à ce point, pas tel qu'il est au
    plan du chantier (D-30)."""
    f = getattr(cap, "obstacles_actifs", None)
    zones = (f(epontilles_en_place) if callable(f)
             else list(getattr(cap, "obstacles", []) or []))
    return Hold(cap.code, list(cap.points), cap.z_min, cap.z_max,
                getattr(cap, "charge_admissible_t_m2", 0.0), cap.name,
                obstacles=[tuple(o) for o in zones if len(o) >= 4],
                zones_charge=list(getattr(cap, "zones_charge", []) or []))


def _plages_y(points, x):
    """Intervalles [y0, y1] où la verticale d'abscisse x traverse le polygone."""
    ys = []
    n = len(points)
    for i in range(n):
        (xa, ya), (xb, yb) = points[i], points[(i + 1) % n]
        if (xa <= x < xb) or (xb <= x < xa):
            t = (x - xa) / (xb - xa)
            ys.append(ya + t * (yb - ya))
    ys.sort()
    return [(ys[i], ys[i + 1]) for i in range(0, len(ys) - 1, 2)]


class CoupeView(QWidget):
    # comme dans la vue navire : un clic sur une cale de la coupe amène le
    # plan sur son pont — c'est souvent d'ici qu'on voit qu'on travaille sur
    # le mauvais niveau
    cale_choisie = Signal(object)

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self.x = 0.0
        self.setMinimumHeight(150)
        self._zones = []          # [(QRectF, capacité)] posées au dessin
        # ce qui est cliquable : par défaut tout ; la vue Chargement n'y met
        # que les cales, pour ne pas promettre un clic qui ne fait rien
        self.cliquable = None
        self.survol = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_x(self, x):
        self.x = float(x)
        self.update()

    # ------------------------------------------------------------- souris
    def _cale_sous(self, pos):
        for rect, cap in self._zones:
            if rect.contains(pos):
                return cap
        return None

    def mouseMoveEvent(self, event):
        cap = self._cale_sous(event.position())
        if cap is not self.survol:
            self.survol = cap
            self.setCursor(Qt.CursorShape.PointingHandCursor if cap
                           else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, event):
        if self.survol is not None:
            self.survol = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        cap = self._cale_sous(event.position())
        if cap is not None:
            self.cale_choisie.emit(cap)

    # ------------------------------------------------------------- données
    def _decks(self):
        return getattr(self.win.project, "sorted_decks", lambda: [])()

    def _flottaison(self):
        """(tirant d'eau à cette abscisse, gîte °) d'après le dernier calcul, ou None.

        Le tirant d'eau local s'interpole entre les deux stations où HAP et HFP
        sont définis (`core.stability.abscisses_tirants_eau`), comme le fait le
        profil : les perpendiculaires ne sont PAS à x = 0, et prendre x/Lpp
        décalait la flottaison de toute la distance du couple 0 à la
        perpendiculaire arrière.

        La gîte reste `None` quand il n'y a **aucun équilibre stable** : la
        transformer en « +0,0° » ferait passer un navire sans équilibre pour un
        navire droit."""
        last = getattr(self.win, "_last", None)
        if not last:
            return None
        _poids, eq, _gz, _rep = last
        h = eq.hydro or {}
        try:
            te_ar = float(h.get("TE_AR_m"))
            te_av = float(h.get("TE_AV_m"))
        except (TypeError, ValueError):
            return None
        nav = getattr(self.win, "nav", None)
        if nav is None:
            return None
        from .core.stability import local_draft
        te = local_draft(nav, self.x, te_ar, te_av)
        return te, getattr(self.win, "_gite", None)

    # ------------------------------------------------------------- dessin
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.BG_DEEP))
        self._zones = []
        decks = self._decks()
        if not decks:
            p.setPen(QColor(theme.TEXT_FAINT))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Aucun pont tracé.")
            p.end()
            return

        # étendue : demi-largeur maximale des contours, et hauteur suffisante
        # pour que la plus haute cale tienne DANS la silhouette — une cale qui
        # déborde du navire dessiné, c'est un dessin qui ment
        demi = 1.0
        z_haut = max(d.z for d in decks) + 1.0
        for d in decks:
            for c in d.capacities:
                z_haut = max(z_haut, c.z_max + 0.6)
                for _x, y in c.points:
                    demi = max(demi, abs(y) + 0.6)
        W, H = self.width(), self.height()
        pad, bas = 30, 66          # `bas` : la place de la règle, des bords et de la note
        scale = min((W - 2 * pad) / (2 * demi), (H - pad - bas) / z_haut)
        cx = W / 2
        base = H - bas

        def px(y, z):
            # BÂBORD À DROITE : la coupe se lit à côté du plan de pont, qui est
            # une vue de dessus étrave à droite — bâbord y est en haut. Une
            # coupe regardée depuis l'arrière mettrait bâbord à gauche et
            # donnerait, d'un panneau à l'autre, une image en miroir (D-25).
            # On regarde donc vers l'arrière, depuis l'avant du repère.
            return QPointF(cx + y * scale, base - z * scale)

        f = QFont()
        f.setPointSize(8)
        p.setFont(f)

        # silhouette schématique : demi-largeur des contours de pont à ce
        # couple, fermée sur la quille
        # les deux murailles, nommées par leur bord et non par leur place à
        # l'écran : le côté d'écran dépend du sens de la coupe, le bord non
        formes = formes_du_bord(dossier_du_navire(self.win))
        reelle = section_relevee(formes, self.x, demi_max=demi, haut_max=z_haut)
        babord, tribord = [], []
        if reelle:
            # le plan des formes décalqué prime : la section vient du trait,
            # plus de la demi-largeur des contours de pont
            par_z = {}
            for y, z in reelle:
                cle = round(z, 4)
                a, b = par_z.get(cle, (y, y))
                par_z[cle] = (min(a, y), max(b, y))
            for z, (y0, y1) in sorted(par_z.items()):
                babord.append((y1, z))
                tribord.append((y0, z))
        else:
            for d in sorted(decks, key=lambda d: d.z):
                contour = next((c for c in d.capacities if c.kind == KIND_CONTOUR and len(c.points) >= 3), None)
                if contour is None:
                    continue
                plages = _plages_y(contour.points, self.x)
                if not plages:
                    continue
                y0 = min(a for a, _b in plages)
                y1 = max(b for _a, b in plages)
                babord.append((y1, d.z))
                tribord.append((y0, d.z))
        if babord:
            haut = max(z_haut - 0.4, babord[-1][1] + 1.0)
            poly = QPolygonF()
            fond_y = 0.55 * abs(babord[0][0])
            poly.append(px(fond_y, 0.0))
            for y, z in babord:
                poly.append(px(y, z))
            poly.append(px(babord[-1][0], haut))
            poly.append(px(tribord[-1][0], haut))
            for y, z in reversed(tribord):
                poly.append(px(y, z))
            poly.append(px(-fond_y, 0.0))
            p.setPen(QPen(QColor(theme.TEXT_FAINT), 1.2))
            p.setBrush(QColor(theme.SURFACE))
            p.drawPolygon(poly)
        # l'axe du navire : sans lui, une cale décalée ne se lit pas
        stylo = QPen(QColor(theme.TEXT_FAINT), 0.9)
        stylo.setStyle(Qt.PenStyle.DashDotLine)
        p.setPen(stylo)
        p.drawLine(px(0.0, 0.0), px(0.0, z_haut))

        # flottaison
        flot = self._flottaison()
        if flot is not None:
            te, gite = flot
            import math
            # sans équilibre stable, on trace la flottaison à plat : on ne
            # sait pas de quel bord le navire se couche, et l'incliner d'un
            # angle inventé serait un dessin qui ment
            dz = 0.0 if gite is None else math.tan(math.radians(gite)) * demi
            p.setPen(QPen(QColor(theme.ACCENT_DARK), 1.4, Qt.PenStyle.DashLine))
            # gîte positive = tribord (y négatif) qui s'enfonce
            p.drawLine(px(demi, te + dz), px(-demi, te - dz))
            p.setPen(QColor(theme.ACCENT_DARK))
            # les étiquettes s'écrivent depuis le bord GAUCHE du dessin, qui
            # est maintenant tribord : ancrées à droite, elles sortaient du cadre
            p.drawText(int(px(-demi, te).x()) + 2, int(px(-demi, te).y()) - 3,
                       f"TE {te:.2f} m")

        # ponts, cales, charges
        cond = getattr(self.win, "condition", None)
        en_place = set(getattr(cond, "epontilles_en_place", []) or [])
        for d in decks:
            p.setPen(QPen(QColor(theme.TEXT_DIM), 1.0))
            p.drawLine(px(demi, d.z), px(-demi, d.z))
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(int(px(-demi, d.z).x()) + 2, int(px(-demi, d.z).y()) - 3,
                       f"{d.name}  Z = {d.z:.2f}")
            for cap in d.capacities:
                if cap.kind == KIND_CONTOUR or len(cap.points) < 3:
                    continue
                for y0, y1 in _plages_y(cap.points, self.x):
                    # normalisé : quel bord tombe à gauche de l'écran dépend
                    # du sens de la coupe, et un rectangle de largeur négative
                    # ne se dessine ni ne se clique correctement
                    r = QRectF(px(y1, cap.z_max), px(y0, cap.z_min)).normalized()
                    if self.cliquable is None or self.cliquable(cap):
                        self._zones.append((r, cap))
                    vise = cap is self.survol
                    p.setPen(QPen(QColor(theme.ACCENT if vise else theme.CAP_EDGE),
                                  2.0 if vise else 1.4))
                    p.setBrush(QColor(theme.CAP_SEL if vise else theme.CAP_BASE))
                    p.drawRect(r)
                    p.setPen(QColor(theme.TEXT_DIM))
                    p.drawText(r.adjusted(4, 2, -4, -2), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                               f"{cap.code} · libre {cap.z_max - cap.z_min:.2f} m")
                # les zones de hauteur libre réduite : on hachure ce qui
                # ENCOMBRE (du plafond bas jusqu'au pont au-dessus), si bien
                # qu'une pile trop haute vient buter dedans à l'écran comme
                # en vrai ; une zone sans hauteur est un mur, hachuré de bas
                # en haut. Sans ce dessin, un décrochement d'un seul bord
                # paraît être une erreur de tracé.
                # une ÉPONTILLE EN PLACE est un mur du plancher au barrot : la
                # coupe la montre comme telle, et la déposer la fait
                # disparaître du dessin comme du contrôle de pose (D-30)
                hold = _hold_de(cap, en_place)
                for o in hold.obstacles:
                    if len(o) < 4:
                        continue
                    ox0, oy0, ox1, oy1 = (float(v) for v in o[:4])
                    if not (min(ox0, ox1) <= self.x <= max(ox0, ox1)):
                        continue
                    libre = _hauteur_libre(o)
                    r = QRectF(px(max(oy0, oy1), cap.z_max),
                               px(min(oy0, oy1), cap.z_min + min(libre, cap.z_max - cap.z_min))
                               ).normalized()
                    teinte = QColor(theme.WARN if libre > 0 else theme.TEXT_FAINT)
                    p.setPen(QPen(teinte, 1.0))
                    p.setBrush(QBrush(teinte, Qt.BrushStyle.FDiagPattern
                                      if libre > 0 else Qt.BrushStyle.BDiagPattern))
                    p.drawRect(r)
                    if r.width() > 26 and libre > 0:
                        p.setPen(teinte.darker(120))
                        p.drawText(r.normalized(), Qt.AlignmentFlag.AlignCenter,
                                   f"libre {libre:.2f}" if r.width() > 60 else f"{libre:.2f}")

                for pl in self.win.condition.placements.get(cap.code, []):
                    x0, y0, x1, y1 = pl.rect
                    if not (x0 <= self.x <= x1):
                        continue
                    # la même couleur que le plan (lot, port ou catégorie)
                    f = getattr(getattr(self.win, "cargo_panel", None),
                                "couleur_charge", None)
                    if f is not None:
                        col = QColor(f(pl))
                    else:
                        from .cargo_panel import _couleur
                        col = _couleur(pl)
                    h = pl.hauteur_m
                    for k in range(max(1, pl.niveaux)):
                        r = QRectF(px(y1, cap.z_min + (k + 1) * h),
                                   px(y0, cap.z_min + k * h)).normalized()
                        p.setPen(QPen(QColor(theme.SURFACE), 0.8))
                        p.setBrush(QColor(col.red(), col.green(), col.blue(), 190))
                        p.drawRect(r)
                    # trop haut pour la hauteur libre À CET ENDROIT (un
                    # barrot bas compte, pas seulement le pont) : cerclé de
                    # rouge, comme sur le plan (D-12 : on signale, on ne
                    # bloque pas)
                    if trop_haut(hold, pl) is not None:
                        haut = cap.z_min + pl.hauteur_totale_m
                        p.setPen(QPen(QColor(theme.DANGER), 1.6))
                        p.setBrush(Qt.BrushStyle.NoBrush)
                        p.drawRect(QRectF(px(y1, haut),
                                          px(y0, cap.z_min)).normalized())

        # cartouche
        p.setPen(QColor(theme.TEXT_DIM))
        couple = self._couple_proche()
        txt = (f"Coupe à x = {self.x:.2f} m" + (f" (≈ {couple})" if couple else "")
               + " — bâbord à droite, comme sur le plan")
        if reelle:
            # le nom du plan décalqué a sa place ici, la ligne du bas est trop
            # étroite pour lui
            source = str(getattr(formes, "source", "") or "").strip()
            if source:
                txt += f" · {source}"
        if flot is not None:
            # même formulation que le profil : « aucun équilibre stable » est
            # un résultat, pas un zéro
            txt += (" · gîte : aucun équilibre stable" if flot[1] is None
                    else f" · gîte {flot[1]:+.1f}°")
        p.drawText(8, 14, txt)
        # règle des demi-largeurs, comme le « meters from CL » de LOCOPIAS
        p.setPen(QPen(QColor(theme.TEXT_FAINT), 0.9))
        y_regle = base + 10
        p.drawLine(int(px(demi, 0).x()), y_regle, int(px(-demi, 0).x()), y_regle)
        pas = 2.0 if demi > 5 else 1.0
        k = 0.0
        while k <= demi:
            for signe in ((1, -1) if k else (1,)):
                ux = px(signe * k, 0).x()
                p.drawLine(int(ux), y_regle - 3, int(ux), y_regle + 3)
                p.drawText(int(ux) - 12, y_regle + 4, 24, 12,
                           Qt.AlignmentFlag.AlignHCenter, f"{k:g}")
            k += pas
        # les deux bords, une ligne sous les graduations : sur une coupe qui
        # tient toute la largeur, l'étiquette recouvrait le dernier chiffre
        p.drawText(6, y_regle + 16, 60, 12, Qt.AlignmentFlag.AlignLeft, "TRIBORD")
        p.drawText(W - 66, y_regle + 16, 60, 12, Qt.AlignmentFlag.AlignRight, "BÂBORD")
        p.setPen(QColor(theme.TEXT_FAINT))
        p.drawText(8, H - 4,
                   f"{nom_du_trace(formes if reelle else None, court=True)} — "
                   "elle situe, elle ne mesure rien. "
                   "Hachuré : plafond bas (hauteur libre réduite) ; rouge : pile trop haute.")
        p.end()

    def _couple_proche(self):
        tc = getattr(self.win, "table_couples", None)
        if not tc:
            return ""
        n = min(range(len(tc)), key=lambda i: abs(tc[i] - self.x))
        return f"C.{n}" if abs(tc[n] - self.x) < 0.7 else ""
