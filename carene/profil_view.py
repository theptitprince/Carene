# -*- coding: utf-8 -*-
"""La situation du navire en un coup d'œil : profil et coupe au maître.

Ce que LOCOPIAS montre en tête de ses résultats — la silhouette avec la
flottaison, les tirants d'eau AR / milieu / AV, l'assiette ; et à côté, une
coupe transversale avec les points K, B, G, G′ et M et l'angle de gîte.

Ce qui est dessiné vient du calcul en cours (`win._last`) et du dossier du
navire : tirants d'eau aux perpendiculaires (table hydrostatique), KB (VCB),
KMt, KG solide et KG effectif (carènes liquides), gîte d'équilibre.

La silhouette est **schématique** : c'est la coque reconstituée depuis les
tables (`core.coque`) — cohérente avec la carène à chaque tirant d'eau, mais
ce n'est pas le plan des formes. Elle situe la flottaison ; elle ne mesure
rien (D-10). Les chiffres, eux, sont ceux du calcul.
"""
from __future__ import annotations

import json
import math
import os

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from . import theme


def coupe_transversale(y, z, gite_rad=0.0):
    """Point (u vers la droite, v vers le haut) de la coupe au maître.

    La coque tourne de la gîte, la flottaison reste horizontale ; gîte positive
    = tribord (y < 0) qui s'enfonce. **Bâbord (y > 0) est à DROITE**, comme la
    coupe du chargement et comme le plan de pont vu de dessus, où bâbord est en
    haut — une coupe retournée d'un panneau à l'autre se lit en miroir (D-25).

    Fonction libre : c'est elle que les tests interrogent, plutôt que de
    mesurer des pixels sur une silhouette schématique.
    """
    ca, sa = math.cos(gite_rad), math.sin(gite_rad)
    return y * ca - z * sa, y * sa + z * ca


# ------------------------------------------------- lecture du plan des formes
# Le module `carene.core.formes` est écrit ailleurs et peut ne pas être là ; le
# fichier peut manquer, être d'une autre version, rendre des points
# invraisemblables. Tout ce qui n'est pas franchement utilisable est écarté sans
# bruit et la reconstitution schématique reprend sa place. Aucun chiffre affiché
# n'en dépend : D-10, ce qu'on décalque sert à la vue, jamais au calcul.
def formes_du_bord(dossier=None):
    """Le plan des formes relevé pour le navire courant, ou None.

    `dossier` : celui du navire ouvert. On le passe explicitement quand on
    l'a — sans lui, il faut relire le fichier de configuration, et ces vues se
    repeignent en continu."""
    try:
        from .core import coque as _coque
        return _coque.formes_du_navire(dossier)
    except Exception:               # pragma: no cover
        return None


def dossier_du_navire(win):
    """Le dossier du navire ouvert dans cette fenêtre, ou None."""
    return getattr(getattr(win, "nav", None), "path", None)


def lire_points(valeur, mini=3):
    """Une liste de couples de flottants, ou None si ça n'en est pas une."""
    try:
        pts = [(float(a), float(b)) for a, b in (valeur or [])]
    except (TypeError, ValueError):
        return None
    return pts if len(pts) >= mini else None


def section_relevee(formes, x_m, demi_max=0.0, haut_max=0.0):
    """La section relevée au couple `x_m`, en (y, z) fermée, ou None.

    `section(x)` d'abord ; à défaut `demi_section(x)`, refermée par son miroir.
    Le résultat n'est retenu que s'il tient dans le navire — un plan mal calé
    ne doit pas dessiner une coque deux fois trop large."""
    if formes is None:
        return None
    pts = None
    try:
        pts = lire_points(formes.section(x_m))
    except Exception:               # pragma: no cover
        pts = None
    if pts is None:
        try:
            demi = lire_points(formes.demi_section(x_m), mini=2)
        except Exception:           # pragma: no cover
            demi = None
        if demi:
            pts = ([(abs(y), z) for y, z in demi]
                   + [(-abs(y), z) for y, z in reversed(demi)])
    if not pts:
        return None
    try:
        demi_max = max(demi_max, float(formes.largeur_max_m()) / 2.0)
    except Exception:               # pragma: no cover
        pass
    haut = haut_max or max(z for _y, z in pts)
    if (max(abs(y) for y, _z in pts) > demi_max * 1.15 + 0.5
            or min(z for _y, z in pts) < -0.5
            or max(z for _y, z in pts) > haut * 1.6 + 1.0):
        return None
    return pts


def nom_du_trace(formes, court=False):
    """« Silhouette schématique », ou le nom du plan quand il est relevé.

    D-10 impose de dire ce qu'on regarde : tant que la forme est reconstituée
    depuis les tables, elle est *schématique* ; dès qu'elle vient d'un plan
    décalqué, c'est ce plan qu'on nomme — et dans les deux cas elle situe sans
    rien mesurer. `court` : sans le nom du plan, pour les cartouches étroits
    (la coupe du chargement), où la ligne serait coupée en plein milieu."""
    if formes is None:
        return "Silhouette schématique"
    source = str(getattr(formes, "source", "") or "").strip()
    return ("Formes relevées" if court or not source
            else f"Formes relevées ({source})")


class ProfilView(QWidget):
    """Profil + coupe au maître, pour la vue Stabilité."""

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self.setMinimumHeight(190)

    # ------------------------------------------------------------- données
    def _coque(self):
        """La coque schématique, prise dans la mémoire du module `core.coque`.

        Elle était auparavant gardée **par instance** : chaque rapport exporté
        construit une `ProfilView` neuve (`rapports.image_profil`), et chacune
        refaisait la reconstitution entière. Elle ne dépend que du navire :
        elle se calcule une fois pour la session."""
        nav = getattr(self.win, "nav", None)
        if nav is None:
            return None
        try:
            from .core import coque as _coque
            return _coque.coque_du_navire(nav)
        except Exception:           # pragma: no cover - la vue ne bloque jamais
            return None

    def _formes(self):
        """Le plan des formes décalqué, s'il a été relevé — sinon None.

        D-10 : il ne sert qu'à DESSINER. Aucun chiffre de la vue n'en dépend ;
        s'il manque, la silhouette schématique reprend sa place."""
        return formes_du_bord(dossier_du_navire(self.win))

    def _section_reelle(self, x_m, coque):
        """La vraie section au couple `x_m`, en (y, z), ou None."""
        return section_relevee(self._formes(), x_m,
                               demi_max=(coque.largeur_m or 0.0) / 2.0,
                               haut_max=coque.creux_m or 0.0)

    def _nom_du_trace(self):
        return nom_du_trace(self._formes())

    def _resultat(self):
        last = getattr(self.win, "_last", None)
        if not last:
            return None
        poids, eq, gz, _rep = last
        h = eq.hydro or {}
        try:
            te_ar = float(h.get("TE_AR_m"))
            te_av = float(h.get("TE_AV_m"))
        except (TypeError, ValueError):
            return None
        d = dict(poids=poids, te_ar=te_ar, te_av=te_av, te_mil=float(eq.draft_m),
                 trim=float(eq.trim_m), gite=getattr(self.win, "_gite", None),
                 kb=h.get("VCB_m"), km=h.get("KMt_m"),
                 kg_eff=getattr(gz, "kg_effectif_m", None),
                 gm_sol=getattr(gz, "gm_solide_m", None),
                 gm_cor=getattr(gz, "gm_corrige_m", None),
                 fiable=getattr(self.win, "_fiable", True))
        try:
            d["kg"] = float(d["km"]) - float(d["gm_sol"])
        except (TypeError, ValueError):
            d["kg"] = None
        return d

    # ------------------------------------------------------------- dessin
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.BG_DEEP))
        f = QFont()
        f.setPointSize(8)
        p.setFont(f)
        res = self._resultat()
        coque = self._coque()
        W, H = self.width(), self.height()
        if coque is None:
            p.setPen(QColor(theme.TEXT_FAINT))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Silhouette indisponible : le navire n'a pas ses tables.")
            p.end()
            return
        # la coupe à gauche (un tiers), le profil à droite
        lc = max(150, min(260, int(W * 0.26)))
        self._dessiner_coupe(p, QRectF(6, 6, lc - 10, H - 12), coque, res)
        self._dessiner_profil(p, QRectF(lc + 4, 6, W - lc - 10, H - 12), coque, res)
        p.end()

    # -- profil ----------------------------------------------------------
    def _dessiner_profil(self, p, zone, coque, res):
        nav = self.win.nav
        from .core.stability import abscisses_tirants_eau
        x_ar, x_av, source = abscisses_tirants_eau(nav)
        # silhouette : la quille entre les perpendiculaires (là où les
        # tirants d'eau sont définis), puis l'étrave et l'arrière rejoignent
        # les extrémités des contours de pont tracés — chaque sommet vient
        # du dossier ou d'un plan calé, rien n'est dessiné « à l'œil ».
        # Les lignes d'eau reconstituées ont toutes la longueur entre
        # perpendiculaires (hypothèse de `core.coque`) : elles ne diraient
        # rien de plus ici.
        bx = coque.bornes_x
        if source != "perpendiculaires":
            x_ar_q, x_av_q = bx
        else:
            x_ar_q, x_av_q = x_ar, x_av
        proj = getattr(self.win, "project", None)
        # La silhouette de la v2.6, et pas autre chose : la quille entre les
        # perpendiculaires, puis pour chaque pont tracé l'étendue de ses
        # contours — arrière montant, pont, avant descendant. Le bord la
        # préfère au livet relevé (qui faisait un escalier) et à la silhouette
        # relevée sur le plan d'ensemble (trop de détail pour situer une
        # flottaison). Elle situe, elle ne mesure rien (D-10).
        profil = [(0.0, x_ar_q, x_av_q)]        # (z, x arrière, x avant)
        for d in (proj.sorted_decks() if proj else []):
            pts = [q for c in d.capacities for q in c.points]
            if pts and d.z > 0.3:
                profil.append((d.z, min(q[0] for q in pts),
                               max(q[0] for q in pts)))
        profil.sort()
        creux = coque.creux_m or (profil[-1][0] + 1.0)
        z_top = max(creux, profil[-1][0] + 0.3)
        x_min = min(q[1] for q in profil) - 1.0
        x_max = max(q[2] for q in profil) + 1.0
        marge_bas = 30
        sc = min(zone.width() / (x_max - x_min),
                 (zone.height() - marge_bas - 16) / (z_top + 0.5))
        ox = zone.left() + (zone.width() - (x_max - x_min) * sc) / 2
        base = zone.bottom() - marge_bas

        def px(x, z):
            return QPointF(ox + (x - x_min) * sc, base - z * sc)

        # coque : quille, arrière montant, pont, avant descendant
        poly = QPolygonF()
        for z, xa, _xf in profil:
            poly.append(px(xa, z))
        poly.append(px(profil[-1][1], z_top))
        poly.append(px(profil[-1][2], z_top))
        for z, _xa, xf in reversed(profil):
            poly.append(px(xf, z))
        p.setPen(QPen(QColor(theme.TEXT_FAINT), 1.2))
        p.setBrush(QColor(theme.SURFACE))
        p.drawPolygon(poly)
        # ponts tracés : un trait par pont, sur la longueur de son contour
        stylo = QPen(QColor(theme.TEXT_FAINT), 0.8)
        stylo.setStyle(Qt.PenStyle.DotLine)
        p.setPen(stylo)
        for d in (proj.sorted_decks() if proj else []):
            pts = [q for c in d.capacities for q in c.points]
            if pts and 0 <= d.z <= z_top:
                p.drawLine(px(min(q[0] for q in pts), d.z),
                           px(max(q[0] for q in pts), d.z))
        # ligne de base
        p.setPen(QPen(QColor(theme.TEXT_FAINT), 0.8))
        p.drawLine(px(x_min, 0), px(x_max, 0))

        if res is None:
            p.setPen(QColor(theme.TEXT_FAINT))
            p.drawText(QRectF(zone.left(), base + 4, zone.width(), 24),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       "Aucun calcul : la flottaison s'affiche dès qu'un équilibre est trouvé.")
            return

        # flottaison : droite par les tirants d'eau aux deux stations connues
        te_ar, te_av = res["te_ar"], res["te_av"]
        if x_av == x_ar:
            x_ar, x_av = profil[0][1], profil[0][2]
        pente = (te_av - te_ar) / (x_av - x_ar)
        z_g = te_ar + pente * (x_min - x_ar)
        z_d = te_ar + pente * (x_max - x_ar)
        couleur = QColor(theme.ACCENT_DARK if res["fiable"] else theme.WARN)
        # l'eau : un voile sous la flottaison, comme dans LOCOPIAS
        eau = QPolygonF([px(x_min, z_g), px(x_max, z_d), px(x_max, -0.3), px(x_min, -0.3)])
        voile = QColor(couleur)
        voile.setAlpha(28)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(voile)
        p.drawPolygon(eau)
        p.setPen(QPen(couleur, 1.6))
        p.drawLine(px(x_min, z_g), px(x_max, z_d))

        # repères de tirants d'eau : AR, milieu, AV, avec la valeur en dessous
        x_mil = (x_ar + x_av) / 2
        p.setFont(QFont(p.font().family(), 8))
        for x, te, nom, fort in ((x_ar, te_ar, "TE AR", False),
                                 (x_mil, res["te_mil"], "TE milieu", True),
                                 (x_av, te_av, "TE AV", False)):
            p.setPen(QPen(QColor(theme.TEXT_DIM), 1.0))
            p.drawLine(px(x, 0), px(x, te + 0.8))
            p.setPen(QColor(theme.TEXT))
            r = QRectF(px(x, 0).x() - 46, base + 3, 92, 26)
            if fort:
                fond = QColor(theme.ACCENT_SOFT)
                p.setBrush(fond)
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(QRectF(r.left() + 8, r.top(), r.width() - 16, 13), 3, 3)
                p.setPen(QColor(theme.ACCENT_DARK))
            p.drawText(r, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       f"{nom} {te:.2f} m")
        # assiette, sous le milieu
        p.setPen(QColor(theme.TEXT_DIM))
        p.drawText(QRectF(px(x_mil, 0).x() - 80, base + 16, 160, 14),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                   f"assiette {res['trim']:+.2f} m"
                   + (" (par l'AR)" if res["trim"] < -1e-3 else
                      " (par l'AV)" if res["trim"] > 1e-3 else ""))
        # cartouche
        p.setPen(QColor(theme.TEXT_DIM))
        p.drawText(int(zone.left()) + 4, int(zone.top()) + 11,
                   f"PROFIL — Δ {res['poids']:,.0f} t".replace(",", " ")
                   + ("" if res["fiable"] else " · hors domaine : valeurs approchées"))
        p.setPen(QColor(theme.TEXT_FAINT))
        # D-10 : on nomme ce qu'on montre. Cette note disait « silhouette
        # schématique » même quand le tracé venait d'un plan décalqué — et le
        # rapport, lui, nommait le plan : la même figure portait deux noms sur
        # la même page (vu en relisant le dossier, D-59).
        note = (f"{self._nom_du_trace()} (perpendiculaires et contours de pont) "
                "— elle situe, elle ne mesure rien.")
        if source == "reperes":
            note += " Flottaison tracée entre les repères de tirants d'eau (perpendiculaires non renseignées)."
        p.drawText(QRectF(zone.left() + 150, zone.top(), zone.width() - 154, 14),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, note)

    # -- coupe au maître -------------------------------------------------
    def _dessiner_coupe(self, p, zone, coque, res):
        # demi-largeurs à mi-longueur, ligne d'eau par ligne d'eau
        xs = coque.bornes_x
        x_mil = (xs[0] + xs[1]) / 2
        reelle = self._section_reelle(x_mil, coque)
        section = []          # (z, demi-largeur)
        if reelle:
            # la vraie section : demi-largeur bâbord, ligne d'eau par ligne d'eau
            par_z = {}
            for y, z in reelle:
                par_z[round(z, 4)] = max(par_z.get(round(z, 4), 0.0), abs(y))
            section = sorted(par_z.items())
        else:
            for l in coque.lignes:
                if l.points:
                    section.append((l.z_m, coque.demi_largeur(x_mil, l.z_m)))
        if not section:
            return
        creux = coque.creux_m or (section[-1][0] + 1.0)
        z_top = max(creux, section[-1][0] + 0.5)
        demi = max(q[1] for q in section) + 0.3
        marge = 26
        sc = min((zone.width() - 2 * marge) / (2 * demi),
                 (zone.height() - 44) / (z_top + 0.6))
        cx = zone.center().x()
        base = zone.bottom() - 22
        gite = res["gite"] if res and res["gite"] is not None else 0.0
        a = math.radians(gite)

        def px(y, z):
            u, v = coupe_transversale(y, z, a)
            return QPointF(cx + u * sc, base - v * sc)

        poly = QPolygonF()
        for z, dl in section:
            poly.append(px(dl, z))                   # bâbord
        poly.append(px(section[-1][1], z_top))
        poly.append(px(-section[-1][1], z_top))
        for z, dl in reversed(section):
            poly.append(px(-dl, z))                  # tribord
        p.setPen(QPen(QColor(theme.TEXT_FAINT), 1.2))
        p.setBrush(QColor(theme.SURFACE))
        p.drawPolygon(poly)

        if res is None:
            p.setPen(QColor(theme.TEXT_FAINT))
            p.drawText(QRectF(zone.left(), zone.top(), zone.width(), 14),
                       Qt.AlignmentFlag.AlignHCenter, "COUPE AU MAÎTRE")
            return

        # flottaison horizontale au tirant d'eau milieu
        te = res["te_mil"]
        couleur = QColor(theme.ACCENT_DARK if res["fiable"] else theme.WARN)
        p.setPen(QPen(couleur, 1.6))
        y_eau = base - te * sc
        p.drawLine(QPointF(zone.left() + 4, y_eau), QPointF(zone.right() - 4, y_eau))
        # les points sur l'axe du navire (qui suit la gîte)
        p.setPen(QPen(QColor(theme.TEXT_DIM), 0.8, Qt.PenStyle.DashDotLine))
        p.drawLine(px(0, -0.2), px(0, z_top + 0.2))
        pts = [("K", 0.0, theme.TEXT_DIM), ("B", res["kb"], theme.TEXT_DIM),
               ("G", res["kg"], theme.DANGER), ("G′", res["kg_eff"], theme.DANGER),
               ("M", res["km"], theme.ACCENT_DARK)]
        # les étiquettes s'empilent à droite de l'axe, du bas vers le haut,
        # sans jamais se chevaucher : G et G′ sont souvent à quelques
        # centimètres l'un de l'autre, M à peine plus haut
        valides = sorted(((float(z), nom, col) for nom, z, col in pts
                          if z is not None), key=lambda q: q[0])
        ys = []
        for z, _n, _c in valides:
            y = px(0, z).y()
            if ys and y > ys[-1] - 11:
                y = ys[-1] - 11
            ys.append(y)
        x_txt = zone.right() - 58
        for (z, nom, col), y in zip(valides, ys):
            c = px(0, z)
            p.setPen(QPen(QColor(col), 1.2))
            p.setBrush(QColor(col))
            p.drawEllipse(c, 2.6, 2.6)
            p.setPen(QPen(QColor(col), 0.7))
            p.drawLine(QPointF(c.x() + 4, c.y()), QPointF(x_txt - 3, y))
            p.setPen(QColor(col))
            p.drawText(QPointF(x_txt, y + 3), f"{nom} {z:.2f}")
        # GM et gîte, en clair
        p.setPen(QColor(theme.TEXT))
        gm = res["gm_cor"]
        titre = f"G′M {gm:.3f} m" if gm is not None else "G′M —"
        p.drawText(QRectF(zone.left(), zone.top(), zone.width(), 14),
                   Qt.AlignmentFlag.AlignHCenter, titre)
        p.setPen(QColor(theme.TEXT_DIM))
        if res["gite"] is None:
            g = "gîte : aucun équilibre stable"
        else:
            g = (f"gîte {abs(gite):.2f}° "
                 + ("tribord" if gite > 0.005 else "bâbord" if gite < -0.005 else "(droit)"))
        p.drawText(QRectF(zone.left(), zone.bottom() - 16, zone.width(), 14),
                   Qt.AlignmentFlag.AlignHCenter, g)
        # de quel bord on est : la coupe a changé de sens en v2.8, on le dit
        # plutôt que de laisser deviner
        p.setPen(QColor(theme.TEXT_FAINT))
        p.drawText(QRectF(zone.left(), zone.bottom() - 30, 44, 12),
                   Qt.AlignmentFlag.AlignLeft, "TRIBORD")
        p.drawText(QRectF(zone.right() - 44, zone.bottom() - 30, 44, 12),
                   Qt.AlignmentFlag.AlignRight, "BÂBORD")
