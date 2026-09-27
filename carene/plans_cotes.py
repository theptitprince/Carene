# -*- coding: utf-8 -*-
"""Plans cotés des cales — la planche qu'on emporte à bord pour vérifier.

Une page par cale, à l'échelle, avec **les cotes que le logiciel utilise
vraiment** : la demi-largeur du contour depuis l'axe du navire (la ligne de
foi), couple par couple, en millimètres, bâbord et tribord. C'est le seul
document qui permette de confronter le décalque au navire avec un mètre : tout
le reste — surfaces, volumes, refus de pose — en découle.

Rien n'est recalculé ici. Le contour dessiné est celui de `geometrie.json`, tel
qu'il sert aux contrôles de pose ; les cotes sont lues dessus. Si une cote est
fausse à bord, c'est le décalque qu'il faut reprendre, pas cette planche.

La feuille est en **A3 paysage**, orientée comme les plans du chantier : étrave
à droite, bâbord en haut. Elle laisse la cale vide exprès — c'est là qu'on
entoure les épontilles.
"""
import os

from PySide6.QtCore import QMarginsF, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen,
)

from . import MENTION, AVERTISSEMENT
from .project import KIND_CONTOUR

# ---------------------------------------------------------------- apparence
C_CONTOUR = QColor("#101418")      # la tôle de la cale
C_COQUE = QColor("#9AA5B1")        # la muraille, pour situer
C_AXE = QColor("#B03030")          # la ligne de foi
C_COUPLE = QColor("#C3CBD4")       # les traits de couples
C_COTE = QColor("#1F4E79")         # les cotes
C_ZONE = QColor("#B8860B")         # les calques (hauteur libre)
C_MUR = QColor("#7A828C")          # les zones interdites : rien ne s'y pose
C_TEXTE = QColor("#1F2A36")
C_GRIS = QColor("#5A6570")

ECHELLES = [20, 25, 30, 40, 50, 60, 75, 80, 100, 125, 150, 200, 250, 300]


def _mm(page, v):
    """Millimètres de papier → pixels du périphérique."""
    return v * page["dpi"] / 25.4


def _nice_echelle(besoin):
    """La plus grande échelle normalisée qui laisse tenir `besoin` (m/mm)."""
    for e in ECHELLES:
        if besoin <= e:
            return e
    return ECHELLES[-1]


# ------------------------------------------------------------------ mesures
def demi_largeurs(points, x, ecart_min=0.005):
    """Les demi-largeurs du contour en x, bâbord et tribord, en mètres.

    On prend la traversée la plus au large de chaque bord : une cote de plan
    mesure la muraille de la cale, pas une découpe intérieure. Sur une
    extrémité — un couple qui tombe pile sur la cloison — on rentre de 5 mm :
    à la cloison même, la moitié des arêtes est verticale et la cote lue n'a
    aucun sens. `None` si le contour ne passe pas par là."""
    xs = [p[0] for p in points]
    x = min(max(x, min(xs) + ecart_min), max(xs) - ecart_min)
    bb = tb = None
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        if (x1 - x) * (x2 - x) > 0 or x1 == x2:
            continue
        y = y1 + (x - x1) / (x2 - x1) * (y2 - y1)
        if y >= 0:
            bb = y if bb is None else max(bb, y)
        else:
            tb = -y if tb is None else max(tb, -y)
    return bb, tb


def cotes_aux_cloisons(points, marge=0.05):
    """Les demi-largeurs aux deux cloisons, prises sur les sommets eux-mêmes.

    L'arête qui ferme une cale n'est presque jamais rigoureusement verticale :
    interpoler dessus donnerait n'importe quoi (sur la cale AR INF, 1547 mm au
    lieu de 5381). On relève donc directement les sommets qui touchent la
    cloison."""
    xs = [p[0] for p in points]
    out = []
    for x_ref, libelle in ((min(xs), "AR"), (max(xs), "AV")):
        proches = [p for p in points if abs(p[0] - x_ref) <= marge]
        bb = max((p[1] for p in proches if p[1] >= 0), default=None)
        tb = max((-p[1] for p in proches if p[1] < 0), default=None)
        out.append((libelle, round(x_ref, 3), bb, tb))
    return out


def cotes_de_la_cale(cap, couples, garde=0.15):
    """Une cote par couple traversant la cale, plus les deux cloisons.

    Un couple qui tombe à moins de `garde` d'une cloison est écarté : la cote
    y serait prise sur l'arête de fermeture, qui ne mesure rien. Les cloisons
    ont leur propre cote, relevée sur les sommets."""
    xs = [p[0] for p in cap.points]
    x0, x1 = min(xs), max(xs)
    ar, av = cotes_aux_cloisons(cap.points)
    out = [ar]
    for n, x in enumerate(couples):
        if x != x or not (x0 + garde <= x <= x1 - garde):
            continue
        bb, tb = demi_largeurs(cap.points, x)
        if bb is None and tb is None:
            continue
        out.append(("C.%d" % n, x, bb, tb))
    out.append(av)
    return out


def _aire(points):
    """Aire du polygone, formule du lacet — la même que celle du solveur."""
    s = 0.0
    n = len(points)
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return abs(s) / 2


# -------------------------------------------------------------------- dessin
def _cadre(painter, page, titre, sous_titre, i, n, navire):
    """En-tête et pied de page, comme les autres documents de Carène."""
    painter.save()
    painter.setPen(C_TEXTE)
    painter.setFont(QFont("Sans Serif", 12, QFont.Weight.Bold))
    lh = painter.fontMetrics().lineSpacing()
    painter.drawText(QRectF(0, 0, page["largeur"], lh),
                     Qt.AlignmentFlag.AlignLeft, titre)
    painter.setFont(QFont("Sans Serif", 9))
    painter.setPen(C_GRIS)
    painter.drawText(QRectF(0, 0, page["largeur"], lh),
                     Qt.AlignmentFlag.AlignRight, navire)
    h2 = painter.fontMetrics().lineSpacing()
    painter.drawText(QRectF(0, lh, page["largeur"], h2),
                     Qt.AlignmentFlag.AlignLeft, sous_titre)
    painter.setFont(QFont("Sans Serif", 7))
    hp = painter.fontMetrics().lineSpacing()
    bas = page["hauteur"] - hp
    painter.drawText(QRectF(0, bas, page["largeur"], hp),
                     Qt.AlignmentFlag.AlignLeft, f"{MENTION} — {AVERTISSEMENT}")
    painter.drawText(QRectF(0, bas, page["largeur"], hp),
                     Qt.AlignmentFlag.AlignRight, f"page {i} / {n}")
    painter.restore()
    return lh + h2 + _mm(page, 3), page["hauteur"] - hp - _mm(page, 2)


def _dessiner_cale(painter, page, haut, bas, cap, contour, couples, note):
    """Une cale à l'échelle, avec ses cotes. Renvoie (échelle, cotes)."""
    xs = [p[0] for p in cap.points]
    ys = [p[1] for p in cap.points]
    x0, x1 = min(xs) - 0.5, max(xs) + 0.5
    y0, y1 = min(ys) - 0.5, max(ys) + 0.5
    # légende + tableau des cotes ; la légende porte une ligne de plus depuis
    # que les murs y ont la leur (voir `_legende`)
    h_bas = _mm(page, 50)
    zone = QRectF(0, haut, page["largeur"], max(_mm(page, 40), bas - haut - h_bas))
    l_dispo = zone.width() / page["dpi"] * 25.4 - 6
    h_dispo = zone.height() / page["dpi"] * 25.4 - 6
    ech = _nice_echelle(max((x1 - x0) * 1000 / max(l_dispo, 1),
                            (y1 - y0) * 1000 / max(h_dispo, 1)))
    ppm = _mm(page, 1000.0 / ech)            # pixels par mètre
    cx = zone.center().x() - (x0 + x1) / 2 * ppm
    cy = zone.center().y() + (y0 + y1) / 2 * ppm

    def P(x, y):
        return QPointF(cx + x * ppm, cy - y * ppm)

    fin = max(1.0, _mm(page, 0.18))
    lignes = cotes_de_la_cale(cap, couples)

    # --- la muraille, en gris : elle situe la cale dans le navire. On la
    # découpe à la zone de dessin, sinon l'étrave part au travers de la page.
    if contour:
        painter.save()
        painter.setClipRect(zone)
        painter.setPen(QPen(C_COQUE, fin))
        pts = [P(*p) for p in contour]
        for a, b in zip(pts, pts[1:] + pts[:1]):
            painter.drawLine(a, b)
        painter.restore()
    # --- les couples
    painter.setPen(QPen(C_COUPLE, fin))
    for _lib, x, bb, tb in lignes:
        painter.drawLine(P(x, y1), P(x, y0))
    # --- les zones de la cale. Deux natures, deux dessins : une zone qui
    # annonce une hauteur libre est un CALQUE (on y pose, une pile trop haute
    # y est signalée — D-21) ; une zone qui n'en annonce pas est un MUR
    # (épontille fixe, puits) où rien ne se pose jamais. Les dessiner toutes
    # en tireté ocre « hauteur libre » faisait passer les murs pour des
    # calques sur la planche qu'on emporte à bord — exactement la planche où
    # l'on vient entourer les épontilles.
    if cap.obstacles:
        from .core.stowage import hauteur_libre_de
        for o in cap.obstacles:
            if len(o) < 4:
                continue
            rect = QRectF(P(o[0], o[3]), P(o[2], o[1]))
            if hauteur_libre_de(o) > 0:
                painter.setPen(QPen(C_ZONE, fin, Qt.PenStyle.DashLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(rect)
                continue
            painter.setPen(QPen(C_MUR, fin))
            painter.setBrush(QBrush(C_MUR, Qt.BrushStyle.BDiagPattern))
            painter.drawRect(rect)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            nom = str(o[4]) if len(o) > 4 and o[4] else ""
            if nom and rect.width() > _mm(page, 12):
                painter.setFont(QFont("Sans Serif", 6))
                painter.setPen(C_MUR)
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, nom)
    # --- le contour de la cale
    painter.setPen(QPen(C_CONTOUR, max(1.0, _mm(page, 0.5))))
    pts = [P(*p) for p in cap.points]
    for a, b in zip(pts, pts[1:] + pts[:1]):
        painter.drawLine(a, b)
    # --- la ligne de foi
    painter.setPen(QPen(C_AXE, fin, Qt.PenStyle.DashDotLine))
    painter.drawLine(P(x0, 0), P(x1, 0))
    painter.setFont(QFont("Sans Serif", 7))
    painter.setPen(C_AXE)
    painter.drawText(QRectF(P(x0, 0).x(), P(x0, 0).y() - _mm(page, 4.5),
                            _mm(page, 30), _mm(page, 4)),
                     Qt.AlignmentFlag.AlignLeft, "axe — ligne de foi")

    # --- les cotes, une par couple et par bord
    painter.setFont(QFont("Sans Serif", 6))
    fm = painter.fontMetrics()
    fleche = _mm(page, 1.4)
    for lib, x, bb, tb in lignes:
        for val, sens in ((bb, +1), (tb, -1)):
            if val is None:
                continue
            painter.setPen(QPen(C_COTE, fin))
            a = P(x, 0)
            b = P(x, sens * val)
            painter.drawLine(a, b)
            for p, dy in ((a, sens), (b, -sens)):
                painter.drawLine(p, p + QPointF(-fleche * 0.4, dy * fleche))
                painter.drawLine(p, p + QPointF(+fleche * 0.4, dy * fleche))
            txt = "%d" % round(val * 1000)
            painter.save()
            painter.translate(P(x, sens * val / 2))
            painter.rotate(-90)
            painter.setPen(C_COTE)
            painter.drawText(QRectF(-fm.horizontalAdvance(txt) / 2 - 2,
                                    -fm.height() - 1,
                                    fm.horizontalAdvance(txt) + 4, fm.height()),
                             Qt.AlignmentFlag.AlignCenter, txt)
            painter.restore()
        painter.setPen(C_GRIS)
        painter.drawText(QRectF(P(x, 0).x() - _mm(page, 6),
                                P(x, 0).y() + _mm(page, 1.2),
                                _mm(page, 12), _mm(page, 3.5)),
                         Qt.AlignmentFlag.AlignCenter, lib)

    # --- les deux cloisons : leur abscisse n'est presque jamais un couple
    painter.setFont(QFont("Sans Serif", 7))
    painter.setPen(C_CONTOUR)
    for x, ali, lib in ((min(xs), Qt.AlignmentFlag.AlignRight, "cloison AR"),
                        (max(xs), Qt.AlignmentFlag.AlignLeft, "cloison AV")):
        painter.drawText(QRectF(P(x, 0).x() - _mm(page, 26), P(x, y0).y(),
                                _mm(page, 52), _mm(page, 4)), ali,
                         "%s  x = %.3f m " % (lib, x) if ali == Qt.AlignmentFlag.AlignRight
                         else " %s  x = %.3f m" % (lib, x))
    return ech, lignes


def _legende(painter, page, y, ech, note):
    """Ce qu'il faut savoir pour lire la planche, et ce qu'on attend en retour."""
    painter.setFont(QFont("Sans Serif", 8))
    h = painter.fontMetrics().lineSpacing()
    painter.setPen(C_TEXTE)
    painter.drawText(QRectF(0, y, page["largeur"], h), Qt.AlignmentFlag.AlignLeft,
                     "Échelle 1/%d · cotes en millimètres depuis l'axe · bâbord en "
                     "haut, étrave à droite (vue de dessus) · trait gris : la "
                     "muraille · tireté ocre : calque de hauteur libre" % ech)
    y += h
    # Le mur a sa ligne à lui : c'est la seule zone où rien ne se pose, et la
    # confondre avec un calque de hauteur libre sur la planche de contrôle
    # ferait entourer la mauvaise chose.
    painter.setPen(C_MUR)
    painter.drawText(QRectF(0, y, page["largeur"], h), Qt.AlignmentFlag.AlignLeft,
                     "Hachuré gris et nommé : zone interdite (épontille fixe, "
                     "puits, descente) — rien ne s'y pose, jamais.")
    y += h
    # La provenance est une phrase entière : elle se replie sur deux lignes
    # plutôt que de sortir de la feuille ou d'être coupée en plein milieu.
    painter.setFont(QFont("Sans Serif", 7))
    hn = painter.fontMetrics().lineSpacing()
    rect = QRectF(0, y, page["largeur"], 2 * hn)
    painter.setPen(C_GRIS)
    painter.drawText(rect, int(Qt.AlignmentFlag.AlignLeft) | int(Qt.TextFlag.TextWordWrap),
                     "Provenance du contour : " + note)
    y += 2 * hn
    painter.setFont(QFont("Sans Serif", 8))
    painter.setPen(C_AXE)
    painter.drawText(QRectF(0, y, page["largeur"], h), Qt.AlignmentFlag.AlignLeft,
                     "À ANNOTER : entourer les ÉPONTILLES FIXES, marquer d'une croix "
                     "les EMPLACEMENTS D'ÉPONTILLES AMOVIBLES, et corriger en rouge "
                     "toute cote démentie par le mètre.")
    return y + h


def _table_cotes(painter, page, y, lignes, aire, z_min, z_max):
    """Le même en chiffres, pour relever au mètre sans mesurer sur la feuille."""
    painter.setFont(QFont("Sans Serif", 7))
    fm = painter.fontMetrics()
    h = fm.height() + _mm(page, 0.8)
    col = page["largeur"] / max(1, len(lignes) + 1)
    titres = ["Repère", "X depuis C.0 (m)", "Bâbord (mm)", "Tribord (mm)"]
    painter.setPen(QPen(C_COUPLE, max(1.0, _mm(page, 0.15))))
    painter.drawRect(QRectF(0, y, page["largeur"], 4 * h))
    for r, t in enumerate(titres):
        painter.setPen(C_GRIS)
        painter.drawText(QRectF(_mm(page, 1), y + r * h, col - _mm(page, 2), h),
                         Qt.AlignmentFlag.AlignLeft, t)
    for c, (lib, x, bb, tb) in enumerate(lignes):
        xr = col * (c + 1)
        painter.setPen(QPen(C_COUPLE, max(1.0, _mm(page, 0.15))))
        painter.drawLine(QPointF(xr, y), QPointF(xr, y + 4 * h))
        vals = [lib, "%.3f" % x,
                "%d" % round(bb * 1000) if bb is not None else "—",
                "%d" % round(tb * 1000) if tb is not None else "—"]
        for r, v in enumerate(vals):
            painter.setPen(C_TEXTE if r > 1 else C_GRIS)
            painter.drawText(QRectF(xr, y + r * h, col - _mm(page, 1), h),
                             Qt.AlignmentFlag.AlignRight, v)
    painter.setPen(C_GRIS)
    painter.drawText(QRectF(0, y + 4 * h + _mm(page, 1), page["largeur"], h),
                     Qt.AlignmentFlag.AlignLeft,
                     "Surface au sol %.2f m² · plancher z = %.3f m · "
                     "plafond z = %.3f m sur ligne de base"
                     % (aire, z_min, z_max))


def exporter(win, chemin, ctx=None):
    """Écrit la planche des plans cotés. Renvoie le chemin."""
    os.makedirs(os.path.dirname(chemin) or ".", exist_ok=True)
    writer = QPdfWriter(chemin)
    _preparer(writer, ctx, win)
    peindre_sur(writer, win, ctx)
    return chemin


def _preparer(device, ctx, win):
    """A3 paysage, 300 dpi : la planche s'emporte à bord, on y lit des
    millimètres. Même réglage pour le PDF et pour l'aperçu avant impression
    (D-62) — l'aperçu doit montrer la planche, pas une autre mise en page."""
    from . import rapports
    device.setPageSize(QPageSize(QPageSize.PageSizeId.A3))
    device.setPageOrientation(QPageLayout.Orientation.Landscape)
    device.setPageMargins(QMarginsF(12, 10, 12, 10), QPageLayout.Unit.Millimeter)
    if isinstance(device, QPdfWriter):
        device.setResolution(300)
        nav = (ctx or rapports.Contexte(win)).navire
        device.setTitle(f"Plans cotés des cales — {nav}")
        device.setCreator(MENTION)


def peindre_sur(device, win, ctx=None):
    """Peint la planche sur un périphérique déjà réglé (PDF ou imprimante).
    Rend le nombre de pages."""
    from . import rapports
    ctx = ctx or rapports.Contexte(win)
    couples = list(getattr(win, "table_couples", None) or [])
    memo = _memo_des_sources(ctx.dossier_navire)

    cales = []
    for deck in win.project.sorted_decks():
        contour = next((c.points for c in deck.capacities
                        if c.kind == KIND_CONTOUR), None)
        for cap in deck.capacities:
            if cap.kind == KIND_CONTOUR or len(cap.points) < 3:
                continue
            cales.append((deck, cap, contour))
    if not cales:
        raise ValueError("aucune cale tracée : pas de plan coté")

    painter = QPainter(device)
    try:
        rect = device.pageLayout().paintRectPixels(device.resolution())
        page = {"largeur": rect.width(), "hauteur": rect.height(),
                "dpi": float(device.resolution())}
        n = len(cales)
        for i, (deck, cap, contour) in enumerate(cales):
            if i:
                device.newPage()
            haut, bas = _cadre(
                painter, page,
                f"{cap.code} — {cap.name}",
                f"{deck.name} · plancher z = {cap.z_min:.3f} m sur ligne de base · "
                f"contour décalqué · repère X depuis C.0, Y positif à bâbord",
                i + 1, n, ctx.navire)
            ech, lignes = _dessiner_cale(painter, page, haut, bas, cap, contour,
                                         couples, memo.get(cap.code, ""))
            y = _legende(painter, page, bas - _mm(page, 50),
                         ech, memo.get(cap.code, "—"))
            _table_cotes(painter, page, y + _mm(page, 2), lignes,
                         _aire(cap.points), cap.z_min, cap.z_max)
        return n
    finally:
        painter.end()


def _memo_des_sources(dossier):
    """La phrase de provenance de chaque cale, telle que l'outil de décalquage
    l'a écrite. On ne la réinvente pas : on la recopie."""
    import json
    chemin = os.path.join(dossier, "plans", "sources_geometrie.json")
    out = {}
    try:
        # `with` : le fichier se referme même si le JSON est illisible — sur
        # Windows, un descripteur laissé ouvert empêche de réécrire le dossier
        with open(chemin, encoding="utf-8") as f:
            memo = json.load(f)
    except (OSError, ValueError):
        return out
    src = (memo.get("sources") or {}).get("cales", "")
    for c in memo.get("cales") or []:
        out[c.get("code")] = c.get("note") or src
    return out
