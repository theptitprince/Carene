# -*- coding: utf-8 -*-
"""Le plan de chargement qu'on tend aux dockers, sur le quai.

« Une fois le chargement calé, il serait sympa de pouvoir imprimer le plan de
chargement pour que les dockers sachent quel colis va où, visuellement. »

Ce n'est pas un document de stabilité : personne, au pied de la coupée, ne
lit un tableau de coordonnées. C'est une **planche par cale**, à l'échelle,
où chaque colis est un rectangle **à la couleur de son lot**, dans son sens,
et rien d'écrit dessus — ce que la vue Chargement montre à l'écran, en plus
gros et en noir sur blanc autour ; le **code couleur** est en tableau sous
la planche, en français sous-titré anglais.

Quatre partis pris, et ils viennent tous du quai :

- **une cale par feuille.** La première version faisait une planche par
  pont ; le bord : « un plan cale par cale pour les dockers ». Sur le quai,
  une équipe travaille UNE cale, et c'est cette feuille-là qu'elle tient. Une
  cale seule sur une A3 se dessine au 1/75 au lieu du 1/125 — 1/150 d'un pont
  entier : la palette fait 16 mm au lieu de 8, on la montre du doigt. Le
  voisinage (cales d'à côté, bordé) reste en gris autour, et une vignette du
  pont dit où l'on est ;
- **la couleur est celle du LOT, toujours.** La vue Chargement laisse choisir
  entre lot, port et catégorie ; le papier n'a qu'un mode, sinon deux
  impressions du même chargement ne se ressemblent pas et personne ne sait
  laquelle croire ;
- **rien n'est écrit sur un colis.** La première version numérotait chaque
  colis (son rang dans le lot) ; le bord l'a refusé : « ça pourrait donner
  une fausse idée de l'ordre de pose, qui n'est pas du tout celui affiché ».
  Sur le quai, un chiffre sur une caisse se lit comme un ordre. La couleur
  est le code ; le tableau du bas dit, par lot, combien de colis, empilés ou
  non, et pour quel port ;
- **l'orientation est celle de l'écran** : arrière à gauche, bâbord en haut,
  avec les deux flèches écrites en clair — en français et en anglais, comme
  tout le texte de la planche, parce que l'équipe du quai ne parle pas
  toujours français. Retourner le plan dans sa tête en le tenant à bout de
  bras est le meilleur moyen de décharger la mauvaise cale.

Rien n'est recalculé ici : les contours viennent de `geometrie.json`, les
colis de la condition du point, les couleurs du manifeste. Le cadre (titre,
sous-titre, pagination, mention légale) est celui de `plans_cotes` — c'est
volontairement le MÊME : deux documents du même dossier qui ne se ressemblent
pas se rangent mal.
"""
import os

from PySide6.QtCore import QPointF, QRectF, QMarginsF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen,
    QPolygonF,
)

from . import MENTION
from .core.stowage import hauteur_libre_de, rect_epontille
# Le cadre de page et la conversion millimètres → pixels sont ceux des plans
# cotés : on ne refait pas un en-tête « presque pareil » à côté de l'autre.
from .plans_cotes import _cadre, _mm, _nice_echelle
from .project import KIND_CONTOUR, epontille_fixe

# ---------------------------------------------------------------- apparence
C_PONT = QColor("#9AA5B1")         # le contour du pont, pour situer
C_CALE = QColor("#101418")         # la tôle des cales
C_FOND = QColor("#F4F6F8")         # le vide d'une cale
C_AXE = QColor("#B03030")          # la ligne de foi
C_COUPLE = QColor("#D5DBE1")       # les repères de couples, légers
C_MUR = QColor("#7A828C")          # zones interdites : rien ne s'y pose
C_ZONE = QColor("#B8860B")         # calques de hauteur libre
C_EPONTILLE = QColor("#101418")    # les épontilles en place
C_TEXTE = QColor("#1F2A36")
C_GRIS = QColor("#5A6570")
C_BLANC = QColor("#FFFFFF")

# Lisible à deux mètres : le code de cale est le seul texte posé sur le plan
# lui-même, tout le reste est dans la légende.
PT_CODE_CALE = 16
PT_TABLEAU = 9        # les tableaux de légende et de synthèse (l'anglais en 7)


def _encre(fond):
    """Noir ou blanc, selon ce qui se voit sur ce fond.

    Les lots prennent des teintes moyennes : le trait intérieur d'une pile,
    tout en blanc, disparaît sur les clairs, tout en noir sur les foncés."""
    lum = (0.299 * fond.red() + 0.587 * fond.green() + 0.114 * fond.blue()) / 255.0
    return QColor(C_TEXTE) if lum > 0.62 else QColor(C_BLANC)


def _abrege_port(ctx, nom):
    """Le port de déchargement en quelques lettres : son code UN/LOCODE quand
    le bord l'a saisi, son nom raccourci sinon.

    Jamais un code deviné (voir `ports.etiquette_de`) : sur un plan de quai,
    un code faux envoie la palette dans le mauvais camion."""
    texte = (nom or "").strip()
    if not texte:
        return ""
    liste = getattr(ctx, "escales", None)
    if liste is not None:
        p = liste.trouver(texte)
        if p is not None and p.code:
            return p.code
    return texte[:6]


# ------------------------------------------------------------------ données
def plan_du_bord(win):
    """Ce que le document a à montrer : `[(pont, contour, [(cale, colis)])]`.

    Les ponts sont dans l'ordre du navire (z croissant), les cales dans
    l'ordre du plan, les colis tels qu'ils sont posés."""
    cond = getattr(win, "condition", None)
    places = dict(getattr(cond, "placements", {}) or {})
    out = []
    for deck in win.project.sorted_decks():
        contour = next((c.points for c in deck.capacities
                        if c.kind == KIND_CONTOUR and len(c.points) >= 3), None)
        cales = [(cap, list(places.get(cap.code) or []))
                 for cap in deck.capacities
                 if cap.kind != KIND_CONTOUR and len(cap.points) >= 3]
        out.append((deck, contour, cales))
    return out


def cales_chargees(plan):
    """Les cales qui portent au moins un colis : celles qui ont une page.

    `[(pont, contour, cales_du_pont, cale, colis)]`, dans l'ordre du navire
    (ponts de bas en haut, cales dans l'ordre du plan). Une cale qui ne porte
    que du matériel du bord a sa page aussi : le chariot qui y dort est un
    obstacle, et la feuille dit qu'il reste à bord."""
    return [(deck, contour, cales, cap, colis)
            for deck, contour, cales in plan
            for cap, colis in cales if colis]


def cales_vides(plan):
    """`[(pont, cale)]` des cales sans rien : pas de feuille, mais la synthèse
    les nomme — le quai doit savoir qu'elles sont vides, pas le deviner."""
    return [(deck, cap) for deck, _contour, cales in plan
            for cap, colis in cales if not colis]


def couleur_du_colis(pl, lots):
    """La couleur du colis sur le papier : celle de son LOT au manifeste.

    Jamais celle du port ni celle de la catégorie : voir l'en-tête du
    module — le papier n'a qu'un mode d'affichage."""
    from .core.cargo_model import couleur_hex
    m = lots.get(getattr(pl, "lot_id", ""))
    if m is not None and getattr(m, "couleur", ""):
        return QColor(m.couleur)
    return QColor(couleur_hex(pl))


def _pieces(colis):
    """Le nombre de colis d'une liste de placements, piles dépliées."""
    return sum(max(1, p.niveaux) for p in colis)


def _lots_poses(cales):
    """`[(cle, nom, [placements])]` des lots posés dans ces cales, dans
    l'ordre où on les rencontre — c'est l'ordre de la légende."""
    ordre, paquets, noms = [], {}, {}
    for _cap, colis in cales:
        for pl in colis:
            cle = pl.lot_id or ("§" + pl.nom)
            if cle not in paquets:
                ordre.append(cle)
                paquets[cle] = []
                noms[cle] = pl.nom
            paquets[cle].append(pl)
    return [(cle, noms[cle], paquets[cle]) for cle in ordre]


# -------------------------------------------------------------- géométrie
MARGE_M = 0.4               # le blanc laissé autour du pont, en mètres navire


# Sur le quai, ce qu'on lit, ce sont les COLIS : l'échelle se cale sur LA
# cale de la feuille, et sur rien d'autre. Sur le navire de référence une
# cale fait 15 à 21 m sur 11 à 12 : seule sur une A3, elle se dessine au 1/75 (la calette au
# 1/40) ; un pont entier tenait au 1/125 – 1/150, un navire entier au 1/200.
# Ce qui dépasse de la feuille — le bordé, les cales voisines — reste dessiné
# en gris et rogné : c'est le décor qui situe, pas ce qu'on lit.
MARGE_CALE_M = 0.8          # ce qu'on montre autour de la cale, en mètres


def _points_de_la_cale(cap):
    """Ce que la planche doit contenir : la cale, plus un peu de voisinage."""
    xs = [p[0] for p in cap.points]
    ys = [p[1] for p in cap.points]
    x0, x1 = min(xs) - MARGE_CALE_M, max(xs) + MARGE_CALE_M
    y0, y1 = min(ys) - MARGE_CALE_M, max(ys) + MARGE_CALE_M
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _repere(page, zone, points, ech=None):
    """(échelle, fonction P) pour dessiner `points` (m) dans `zone` (pixels).

    Orientation de l'écran (`DeckStowView.to_px`) : X croissant vers la
    droite — l'avant —, Y croissant vers le haut — bâbord. `ech` forcée quand
    l'échelle a déjà été arrêtée sur une autre zone (voir `_zone_utile`)."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, x1 = min(xs) - MARGE_M, max(xs) + MARGE_M
    y0, y1 = min(ys) - MARGE_M, max(ys) + MARGE_M
    if ech is None:
        l_dispo = zone.width() / page["dpi"] * 25.4 - 6
        h_dispo = zone.height() / page["dpi"] * 25.4 - 6
        ech = _nice_echelle(max((x1 - x0) * 1000 / max(l_dispo, 1),
                                (y1 - y0) * 1000 / max(h_dispo, 1)))
    ppm = _mm(page, 1000.0 / ech)
    cx = zone.center().x() - (x0 + x1) / 2 * ppm
    cy = zone.center().y() + (y0 + y1) / 2 * ppm

    def P(x, y):
        return QPointF(cx + x * ppm, cy - y * ppm)

    return ech, P


def _zone_utile(page, dispo, points, ech):
    """La place que la cale occupe VRAIMENT à cette échelle.

    Une cale deux fois plus longue que large, dessinée à l'échelle qui tient
    en largeur, n'occupe pas toute la hauteur : centrée dans toute la place
    disponible, elle laisserait du blanc entre le dessin et sa légende, qui
    vont pourtant ensemble. On colle donc le plan en haut et la légende juste
    dessous. Le blanc qui reste est en bas, d'un seul tenant — et sur le
    quai, c'est là qu'on écrit au crayon."""
    ys = [p[1] for p in points]
    ppm = _mm(page, 1000.0 / ech)
    # + la bande où s'écrit le code de la cale, au-dessus d'elle
    besoin = (max(ys) - min(ys) + 2 * MARGE_M) * ppm + _mm(page, 14)
    return QRectF(dispo.left(), dispo.top(), dispo.width(),
                  max(_mm(page, 40), min(dispo.height(), besoin)))


def _rect(P, x0, y0, x1, y1):
    """Le rectangle de page d'une boîte navire, coins remis d'équerre."""
    a = P(min(x0, x1), max(y0, y1))
    b = P(max(x0, x1), min(y0, y1))
    return QRectF(a, b).normalized()


# ---------------------------------------------------------------- la cale
def _dessiner_cale(painter, page, zone, ech, contour, cales, cap, colis,
                   couples, lots, ctx):
    """Une planche de cale : le voisinage en gris, LA cale, ses colis."""
    pts = _points_de_la_cale(cap)
    _ech, P = _repere(page, zone, pts, ech)
    fin = max(1.0, _mm(page, 0.18))

    painter.save()
    painter.setClipRect(zone)

    # --- le décor, en gris : le contour du pont et les cales voisines. Ils
    # dépassent presque toujours de la feuille, c'est voulu — ce qu'on en
    # voit dit de quel côté est le bordé et où commence la cale d'à côté.
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if contour:
        painter.setPen(QPen(C_PONT, max(1.0, _mm(page, 0.35))))
        painter.drawPolygon(QPolygonF([P(*p) for p in contour]))
    painter.setFont(QFont("Sans Serif", 11, QFont.Weight.Bold))
    for autre, _colis in cales:
        if autre is cap:
            continue
        painter.setPen(QPen(C_PONT, max(1.0, _mm(page, 0.3)), Qt.PenStyle.DashLine))
        painter.drawPolygon(QPolygonF([P(*p) for p in autre.points]))
        # son code, s'il tombe sur la feuille : un demi-mot rogné au bord
        # n'aide personne
        cx = sum(p[0] for p in autre.points) / len(autre.points)
        cy = sum(p[1] for p in autre.points) / len(autre.points)
        c = P(cx, cy)
        r = QRectF(c.x() - _mm(page, 15), c.y() - _mm(page, 4), _mm(page, 30), _mm(page, 8))
        if zone.contains(r):
            painter.setPen(C_PONT)
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter, autre.code)

    # --- les repères de couples : légers, ils servent à situer, pas à coter.
    # Un couple sur cinq porte son numéro.
    xs_pont = [p[0] for p in pts]
    ys_pont = [p[1] for p in pts]
    painter.setFont(QFont("Sans Serif", 7))
    for n, x in enumerate(couples or []):
        if x != x or not (min(xs_pont) <= x <= max(xs_pont)):
            continue
        painter.setPen(QPen(C_COUPLE, fin))
        painter.drawLine(P(x, max(ys_pont)), P(x, min(ys_pont)))
        if n % 5:
            continue
        painter.setPen(C_GRIS)
        painter.drawText(QRectF(P(x, min(ys_pont)).x() - _mm(page, 6),
                                P(x, min(ys_pont)).y(), _mm(page, 12), _mm(page, 4)),
                         Qt.AlignmentFlag.AlignCenter, "C.%d" % n)

    # --- la cale : le vide d'abord, la marchandise ensuite
    painter.setPen(QPen(C_CALE, max(1.2, _mm(page, 0.5))))
    painter.setBrush(QBrush(C_FOND))
    painter.drawPolygon(QPolygonF([P(*p) for p in cap.points]))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    # structure et calques : un mur se hachure et se lit comme un mur
    for o in getattr(cap, "obstacles", []) or []:
        if len(o) < 4:
            continue
        r = _rect(P, float(o[0]), float(o[1]), float(o[2]), float(o[3]))
        if hauteur_libre_de(o) > 0:
            painter.setPen(QPen(C_ZONE, fin, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        else:
            painter.setPen(QPen(C_MUR, fin))
            painter.setBrush(QBrush(C_MUR, Qt.BrushStyle.BDiagPattern))
        painter.drawRect(r)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    # --- la ligne de foi, si elle traverse la feuille : le seul repère qui
    # dit où est l'axe du navire
    if min(ys_pont) <= 0 <= max(ys_pont):
        painter.setPen(QPen(C_AXE, fin, Qt.PenStyle.DashDotLine))
        painter.drawLine(P(min(xs_pont), 0), P(max(xs_pont), 0))

    # --- les colis, à l'échelle, à la couleur de leur lot
    for pl in colis:
        _dessiner_colis(painter, page, P, pl, lots)

    # --- les épontilles EN PLACE : de petits carrés noirs, par-dessus la
    # marchandise. Une épontille qu'on ne voit pas est une épontille qu'un
    # chariot emboutit.
    _dessiner_epontilles(painter, page, P, [(cap, colis)], _en_place(ctx.win))

    # --- le code de la cale, en gros et par-dessus tout : c'est le premier
    # mot que le docker cherche sur la feuille
    painter.setFont(QFont("Sans Serif", PT_CODE_CALE, QFont.Weight.Bold))
    fm = painter.fontMetrics()
    cxs = [p[0] for p in cap.points]
    cys = [p[1] for p in cap.points]
    coin = P(min(cxs), max(cys))
    larg = fm.horizontalAdvance(cap.code) + _mm(page, 3)
    haut = fm.height() + _mm(page, 1)
    r = QRectF(coin.x(), coin.y() - haut - _mm(page, 0.8), larg, haut)
    if r.top() < zone.top():          # pas de place au-dessus : dedans
        r.moveTop(coin.y() + _mm(page, 0.8))
    painter.setPen(QPen(C_CALE, fin))
    painter.setBrush(QBrush(C_BLANC))
    painter.drawRect(r)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(C_CALE)
    painter.drawText(r, Qt.AlignmentFlag.AlignCenter, cap.code)

    _fleches(painter, page, zone)
    painter.restore()


def _vignette(painter, page, cadre, deck, contour, cales, cap):
    """La vignette de situation : le pont entier en petit, cette cale en noir.

    Le code de cale suffit à qui connaît le navire ; l'équipe de quai, elle,
    le découvre le matin même. Trois centimètres de pont avec la cale noircie
    disent « arrière, bâbord » sans un mot. Sans contour de pont tracé, les
    cales seules font le pont."""
    pts = list(contour) if contour else [p for c, _colis in cales for p in c.points]
    if not pts:
        return
    painter.save()
    painter.setPen(QPen(C_COUPLE, max(1.0, _mm(page, 0.2))))
    painter.setBrush(QBrush(C_BLANC))
    painter.drawRect(cadre)
    painter.setClipRect(cadre)
    painter.setFont(QFont("Sans Serif", 7))
    painter.setPen(C_GRIS)
    painter.drawText(cadre.adjusted(_mm(page, 1.5), _mm(page, 0.5), 0, 0),
                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                     "%s — situation / location" % deck.name)
    dessin = cadre.adjusted(_mm(page, 2), _mm(page, 5), -_mm(page, 2), -_mm(page, 2))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    ppm = min(dessin.width() / max(max(xs) - min(xs), 1e-6),
              dessin.height() / max(max(ys) - min(ys), 1e-6))
    cx = dessin.center().x() - (min(xs) + max(xs)) / 2 * ppm
    cy = dessin.center().y() + (min(ys) + max(ys)) / 2 * ppm

    def P(x, y):
        return QPointF(cx + x * ppm, cy - y * ppm)

    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(C_PONT, max(1.0, _mm(page, 0.25))))
    if contour:
        painter.drawPolygon(QPolygonF([P(*p) for p in contour]))
    for autre, _colis in cales:
        painter.drawPolygon(QPolygonF([P(*p) for p in autre.points]))
    painter.setPen(QPen(C_CALE, max(1.0, _mm(page, 0.25))))
    painter.setBrush(QBrush(C_CALE))
    painter.drawPolygon(QPolygonF([P(*p) for p in cap.points]))
    painter.restore()


def _en_place(win):
    """Les épontilles en place au point : celles de la condition, plus les
    FIXES du navire — celles-là sont de la structure (voir `cargo_panel`)."""
    cond = getattr(win, "condition", None)
    ids = set(getattr(cond, "epontilles_en_place", None) or [])
    proj = getattr(win, "project", None)
    if proj is not None and hasattr(proj, "epontilles_fixes"):
        ids |= proj.epontilles_fixes()
    return ids


def _dessiner_epontilles(painter, page, P, cales, ids):
    """Les épontilles en place, en carrés noirs pleins.

    Les épontilles DÉPOSÉES ne sont pas dessinées : sur le quai, tout ce qui
    est noir est un obstacle réel — un repère pâle « elle pourrait aller là »
    n'a de sens que dans l'éditeur du bord."""
    mini = _mm(page, 1.8)
    painter.setPen(QPen(C_EPONTILLE, max(1.0, _mm(page, 0.2))))
    painter.setBrush(QBrush(C_EPONTILLE))
    for cap, _colis in cales:
        for e in getattr(cap, "epontilles", []) or []:
            if not (e.get("id") in ids or epontille_fixe(e)):
                continue
            x0, y0, x1, y1 = rect_epontille(e)[:4]
            r = _rect(P, x0, y0, x1, y1)
            if r.width() < mini:
                r.adjust(-(mini - r.width()) / 2, 0, (mini - r.width()) / 2, 0)
            if r.height() < mini:
                r.adjust(0, -(mini - r.height()) / 2, 0, (mini - r.height()) / 2)
            painter.drawRect(r)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _dessiner_colis(painter, page, P, pl, lots):
    """Un colis : un rectangle à l'échelle, dans son sens, à la couleur de son
    lot — et RIEN D'ÉCRIT DESSUS.

    La première version numérotait les colis (leur rang dans le lot). Le bord
    l'a refusé : « ça pourrait donner une fausse idée de l'ordre de pose, qui
    n'est pas du tout celui affiché ». Sur le quai, un chiffre sur une caisse
    se lit comme un ordre. La couleur suffit à dire le lot ; le tableau sous
    le plan porte les comptes, l'empilement et les ports. Une pile se
    reconnaît à son trait doublé, sans chiffre."""
    x0, y0, x1, y1 = pl.rect
    r = _rect(P, x0, y0, x1, y1)
    fond = couleur_du_colis(pl, lots)
    painter.setBrush(QBrush(fond, Qt.BrushStyle.BDiagPattern
                            if pl.est_materiel_bord else Qt.BrushStyle.SolidPattern))
    stylo = QPen(C_CALE, max(1.0, _mm(page, 0.2)))
    if pl.est_materiel_bord:
        stylo.setStyle(Qt.PenStyle.DashLine)
    painter.setPen(stylo)
    painter.drawRect(r)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if pl.niveaux > 1:
        # une pile : un second trait à l'intérieur — visible à toute échelle,
        # et ce n'est pas un chiffre
        creux = max(1.0, _mm(page, 0.5))
        painter.setPen(QPen(_encre(fond), max(1.0, _mm(page, 0.15))))
        painter.drawRect(r.adjusted(creux, creux, -creux, -creux))


def _fleches(painter, page, zone):
    """« AVANT → » et « BÂBORD ↑ » : l'orientation écrite en clair.

    Un plan de pont n'a ni étrave ni nom de bord dessiné dessus ; sans ces
    deux mots, une planche tenue à bout de bras se lit dans le mauvais sens
    une fois sur deux."""
    painter.setFont(QFont("Sans Serif", 10, QFont.Weight.Bold))
    painter.setPen(C_GRIS)
    h = painter.fontMetrics().height()
    painter.drawText(QRectF(zone.right() - _mm(page, 70), zone.bottom() - h,
                            _mm(page, 70), h),
                     Qt.AlignmentFlag.AlignRight, "AVANT / FORWARD →")
    painter.drawText(QRectF(zone.left(), zone.top(), _mm(page, 70), h),
                     Qt.AlignmentFlag.AlignLeft, "BÂBORD / PORT SIDE ↑")


# --------------------------------------------------------------- légendes
def _pastille(painter, page, x, y, couleur, hachure=False):
    """La tache de couleur qui précède un lot dans la légende."""
    c = _mm(page, 3.4)
    r = QRectF(x, y, c, c)
    painter.setPen(QPen(C_CALE, max(1.0, _mm(page, 0.2))))
    painter.setBrush(QBrush(couleur, Qt.BrushStyle.BDiagPattern if hachure
                            else Qt.BrushStyle.SolidPattern))
    painter.drawRect(r)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    return r.right() + _mm(page, 2)


def _empilement(colis):
    """Ce que la colonne « Empilés / Stacked » dit d'un lot sur ce pont."""
    hauts = sorted({int(p.niveaux) for p in colis if p.niveaux > 1})
    if not hauts:
        return "non / no"
    if len(hauts) == 1:
        return "oui ×%d / yes ×%d" % (hauts[0], hauts[0])
    return "oui ×%d–×%d / yes" % (hauts[0], hauts[-1])


ENTETES_LOTS = [("Lot", "Lot"), ("Colis dans la cale", "Packages in the hold"),
                ("Au lot", "In the lot"), ("Empilés", "Stacked"),
                ("Tonnage (t)", "Weight (t)"), ("Chargé à", "Loaded at"),
                ("Déchargé à", "Discharged at")]
# Les colonnes en millimètres, pas en fraction de la feuille : sur une A3
# paysage, un tableau étiré sur 400 mm met un demi-mètre entre le nom du lot
# et son compte, et l'œil perd la ligne. Et la vignette de situation prend
# les 100 mm de droite.
LARGEURS_LOTS_MM = [58, 36, 24, 30, 28, 54, 54]
LARGEUR_VIGNETTE_MM = 100
HAUTEUR_VIGNETTE_MM = 26


def _legende_cale(painter, page, y, deck, contour, cales, cap, colis, lots, ctx, ech):
    """Sous le plan : le CODE COULEUR en tableau, français sous-titré anglais,
    et la vignette de situation à droite.

    Le bord : « le code couleur peut être affiché dessous avec le nombre de
    colis et stacké ou non (tableau en français sous-titré anglais) ». Le
    quai n'est pas toujours francophone ; chaque intitulé porte donc sa
    traduction en petit gris, et les cellules qui le demandent (oui / no)
    aussi. Un tableau : les lots de CETTE cale (pastille, nom, compte dans la
    cale et au lot, empilement, tonnage, ports), puis le total de la cale."""
    painter.setFont(QFont("Sans Serif", 8))
    lh = painter.fontMetrics().lineSpacing()
    painter.setPen(C_GRIS)
    painter.drawText(QRectF(0, y, page["largeur"], lh), Qt.AlignmentFlag.AlignLeft,
                     "Échelle 1/%d · arrière à gauche, bâbord en haut · un rectangle = "
                     "un colis, à la couleur de son lot, dans son sens · trait doublé = "
                     "pile · hachuré : matériel du bord · carré noir : épontille en "
                     "place · gris hachuré : zone interdite · pointillé gris : cale "
                     "voisine" % ech)
    y += lh
    painter.setFont(QFont("Sans Serif", 7))
    lh2 = painter.fontMetrics().lineSpacing()
    painter.setPen(C_GRIS)
    painter.drawText(QRectF(0, y, page["largeur"], lh2), Qt.AlignmentFlag.AlignLeft,
                     "Scale 1/%d · aft on the left, port side up · one rectangle = one "
                     "package, in its lot colour, as it lies · double line = stack · "
                     "hatched: ship's gear · black square: pillar in place · grey "
                     "hatch: no-go area · grey dashes: next hold" % ech)
    y += lh2 + _mm(page, 1.5)

    # --- la vignette, à droite du tableau
    _vignette(painter, page,
              QRectF(page["largeur"] - _mm(page, LARGEUR_VIGNETTE_MM), y,
                     _mm(page, LARGEUR_VIGNETTE_MM), _mm(page, HAUTEUR_VIGNETTE_MM)),
              deck, contour, cales, cap)

    # --- les lots de la cale
    hh = _titre_bilingue(painter, page, y, "Les lots dans cette cale",
                         "Lots in this hold")
    y += hh
    rangs, pastilles = [], []
    for cle, nom, lot in _lots_poses([(cap, colis)]):
        pl = lot[0]
        m = lots.get(getattr(pl, "lot_id", ""))
        ici = _pieces(lot)
        tonnes = sum(p.poids_total_t for p in lot)
        pastilles.append((couleur_du_colis(pl, lots), pl.est_materiel_bord))
        if pl.est_materiel_bord:
            rangs.append((nom, "%d" % ici, "—", _empilement(lot), "%.2f" % tonnes,
                          "matériel du bord / ship's gear", "reste à bord / stays on board"))
        else:
            total = getattr(m, "quantite", None) or ici
            rangs.append((nom, "%d" % ici, "%d" % total, _empilement(lot),
                          "%.2f" % tonnes,
                          _texte_port(ctx, getattr(m, "port_chargement", "")
                                      or getattr(pl, "port_chargement", "")),
                          _texte_port(ctx, getattr(m, "port_dechargement", "")
                                      or getattr(pl, "port_dechargement", ""))))
    y = _tableau(painter, page, y, page["hauteur"], ENTETES_LOTS,
                 _parts(page, LARGEURS_LOTS_MM), rangs, num=(1, 2, 4),
                 pastilles=pastilles, retrait=_mm(page, 6))

    # --- le total de la cale, en une ligne, dans les deux langues
    y += _mm(page, 1.5)
    marchand = [p for p in colis if not p.est_materiel_bord]
    bord = [p for p in colis if p.est_materiel_bord]
    painter.setFont(QFont("Sans Serif", PT_TABLEAU, QFont.Weight.Bold))
    lh = painter.fontMetrics().lineSpacing()
    painter.setPen(C_TEXTE)
    texte = "Cale %s%s · %s : %d colis · %.2f t" % (
        cap.code, " — %s" % cap.name if cap.name else "", deck.name,
        _pieces(marchand), sum(p.poids_total_t for p in marchand))
    if bord:
        texte += " · + %d pièce(s) de matériel du bord (%.2f t), qui reste à bord" % (
            _pieces(bord), sum(p.poids_total_t for p in bord))
    painter.drawText(QRectF(0, y, page["largeur"], lh), Qt.AlignmentFlag.AlignLeft, texte)
    y += lh
    painter.setFont(QFont("Sans Serif", 7))
    lh2 = painter.fontMetrics().lineSpacing()
    painter.setPen(C_GRIS)
    texte = "Hold %s: %d packages · %.2f t" % (
        cap.code, _pieces(marchand), sum(p.poids_total_t for p in marchand))
    if bord:
        texte += " · + %d piece(s) of ship's gear (%.2f t), staying on board" % (
            _pieces(bord), sum(p.poids_total_t for p in bord))
    painter.drawText(QRectF(0, y, page["largeur"], lh2), Qt.AlignmentFlag.AlignLeft, texte)
    return y + lh2


def _parts(page, largeurs_mm):
    """Des largeurs de colonnes en millimètres → les fractions de la feuille
    que `_tableau` attend."""
    return [_mm(page, w) / page["largeur"] for w in largeurs_mm]


def _titre_bilingue(painter, page, y, fr, en):
    """Un titre de tableau : le français en gras, l'anglais en petit gris à sa
    suite — placé d'après la largeur MESURÉE du français, pas à un décalage
    fixe qui mord sur les titres longs. Renvoie la hauteur prise."""
    painter.setFont(QFont("Sans Serif", 10, QFont.Weight.Bold))
    hh = painter.fontMetrics().lineSpacing()
    larg = painter.fontMetrics().horizontalAdvance(fr)
    painter.setPen(C_TEXTE)
    painter.drawText(QRectF(0, y, page["largeur"], hh), Qt.AlignmentFlag.AlignLeft, fr)
    painter.setFont(QFont("Sans Serif", 7))
    painter.setPen(C_GRIS)
    painter.drawText(QRectF(larg + _mm(page, 3), y, page["largeur"], hh),
                     Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, en)
    return hh


def _texte_port(ctx, nom):
    """Un port tel qu'il s'écrit dans les documents : « FRLEH — Le Havre »."""
    from . import ports as _ports
    return _ports.etiquette_de(getattr(ctx, "escales", None), nom) or "—"


def _hauteur_legende(page, painter, colis):
    """La place à réserver en bas de page pour la légende de la cale : deux
    lignes de conventions, un titre, un tableau à en-tête double, le total
    sur deux lignes — et jamais moins que la vignette."""
    painter.setFont(QFont("Sans Serif", PT_TABLEAU))
    lh = painter.fontMetrics().lineSpacing()
    lignes = len(_lots_poses([(None, colis)])) + 7
    return min(page["hauteur"] * 0.45,
               max(lignes * (lh + _mm(page, 0.6)) + _mm(page, 14),
                   _mm(page, HAUTEUR_VIGNETTE_MM + 14)))


# --------------------------------------------------------------- synthèse
def _page_synthese(painter, page, haut, bas, ctx, plan, lots):
    """La page de tête : le point, la voilure, et qui va où.

    C'est la feuille que le chef de bord garde en main pendant que chaque
    équipe tient sa cale : elle dit ce qui est posé, dans quelle cale, quelles
    cales restent vides, et — le seul chiffre que le quai réclame vraiment —
    **ce qui reste à quai**."""
    p = ctx.point
    y = haut
    painter.setFont(QFont("Sans Serif", 13, QFont.Weight.Bold))
    painter.setPen(C_TEXTE)
    lh = painter.fontMetrics().lineSpacing()
    painter.drawText(QRectF(0, y, page["largeur"], lh), Qt.AlignmentFlag.AlignLeft,
                     "%s — point %d%s" % (ctx.navire, p.numero,
                                          " · %s" % p.libelle if p.libelle else ""))
    y += lh
    painter.setFont(QFont("Sans Serif", 10))
    lh = painter.fontMetrics().lineSpacing()
    painter.setPen(C_GRIS)
    lignes = ["Lieu : %s · date du point : %s" % (p.lieu, p.date_lisible)
              if p.lieu else "Date du point : %s" % p.date_lisible]
    if ctx.voilure:
        lignes.append("Voilure portée : %s" % ctx.voilure)
    # « page 2 : cale 1040 (Pont inférieur) » : sur le quai, on distribue les
    # planches une par équipe et il faut pouvoir dire laquelle sans les
    # feuilleter
    suite = ["page %d : cale %s (%s)" % (i + 2, cap.code, deck.name)
             for i, (deck, _c, _cales, cap, _colis) in enumerate(cales_chargees(plan))]
    if suite:
        lignes.append("Les planches / the sheets : " + " · ".join(suite))
    vides = cales_vides(plan)
    if vides:
        lignes.append("Cales vides, sans planche / empty holds, no sheet : "
                      + " · ".join("%s (%s)" % (cap.code, deck.name)
                                   for deck, cap in vides))
    for t in lignes:
        r = painter.boundingRect(QRectF(0, y, page["largeur"], lh * 4),
                                 Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, t)
        painter.drawText(QRectF(0, y, page["largeur"], r.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, t)
        y += r.height()
    y += _mm(page, 4)
    painter.setFont(QFont("Sans Serif", 11))
    lh = painter.fontMetrics().lineSpacing()

    # --- le tableau : un lot, une cale, ce qu'il y a dedans
    rangs = []
    for deck, _contour, cales in plan:
        for cap, colis in cales:
            for cle, nom, lot in _lots_poses([(cap, colis)]):
                pl = lot[0]
                m = lots.get(getattr(pl, "lot_id", ""))
                rangs.append((nom, cap.code, deck.name, _pieces(lot),
                              sum(q.poids_total_t for q in lot),
                              "matériel du bord" if pl.est_materiel_bord
                              else _texte_port(ctx, getattr(m, "port_dechargement", "")
                                               or getattr(pl, "port_dechargement", ""))))
    rangs.sort(key=lambda r: (r[0], r[2], r[1]))

    if not rangs:
        painter.setFont(QFont("Sans Serif", 12, QFont.Weight.Bold))
        painter.setPen(C_AXE)
        painter.drawText(QRectF(0, y, page["largeur"], lh * 2),
                         Qt.AlignmentFlag.AlignLeft,
                         "AUCUN COLIS POSÉ : il n'y a pas de plan à porter au quai.")
        y += lh * 2
    else:
        y = _tableau(painter, page, y, bas - _mm(page, 30),
                     [("Lot", "Lot"), ("Cale", "Hold"), ("Pont", "Deck"),
                      ("Colis", "Packages"), ("Tonnage (t)", "Weight (t)"),
                      ("Port de déchargement", "Discharge port")],
                     _parts(page, [90, 30, 50, 30, 36, 110]),
                     [(r[0], r[1], r[2], "%d" % r[3], "%.2f" % r[4], r[5])
                      for r in rangs], num=(3, 4))
    y += _mm(page, 3)

    # --- les totaux : posé, manifeste, et ce qui reste à quai
    marchand = [p for _d, _c, cales in plan for _cap, colis in cales
                for p in colis if not p.est_materiel_bord]
    bord = [p for _d, _c, cales in plan for _cap, colis in cales
            for p in colis if p.est_materiel_bord]
    pose = _pieces(marchand)
    manifeste = sum(int(m.quantite) for m in (ctx.win.condition.manifeste or []))
    painter.setFont(QFont("Sans Serif", 11, QFont.Weight.Bold))
    lh = painter.fontMetrics().lineSpacing()
    painter.setPen(C_TEXTE)
    tonnes = sum(p.poids_total_t for p in marchand)
    painter.drawText(QRectF(0, y, page["largeur"], lh), Qt.AlignmentFlag.AlignLeft,
                     "Total posé : %d colis · %.2f t — total manifeste : %d colis"
                     % (pose, tonnes, manifeste))
    y += lh
    painter.setFont(QFont("Sans Serif", 8))
    lh_en = painter.fontMetrics().lineSpacing()
    painter.setPen(C_GRIS)
    painter.drawText(QRectF(0, y, page["largeur"], lh_en), Qt.AlignmentFlag.AlignLeft,
                     "Total loaded: %d packages · %.2f t — manifest total: %d packages"
                     % (pose, tonnes, manifeste))
    y += lh_en
    reste = manifeste - pose
    painter.setFont(QFont("Sans Serif", 11, QFont.Weight.Bold))
    painter.setPen(C_AXE if reste > 0 else C_GRIS)
    painter.drawText(QRectF(0, y, page["largeur"], lh), Qt.AlignmentFlag.AlignLeft,
                     "Reste à quai : %d colis" % max(0, reste) if reste >= 0 else
                     "Reste à quai : 0 colis (%d colis posés de plus que le "
                     "manifeste — à vérifier)" % (-reste))
    y += lh
    painter.setFont(QFont("Sans Serif", 8))
    painter.setPen(C_GRIS)
    painter.drawText(QRectF(0, y, page["largeur"], lh_en), Qt.AlignmentFlag.AlignLeft,
                     "Left on the quay: %d packages" % max(0, reste))
    y += lh_en
    if bord:
        painter.setFont(QFont("Sans Serif", 9))
        painter.setPen(C_GRIS)
        painter.drawText(QRectF(0, y, page["largeur"],
                                painter.fontMetrics().lineSpacing()),
                         Qt.AlignmentFlag.AlignLeft,
                         "En plus, hors manifeste : %d pièce(s) de matériel du bord "
                         "(hachuré sur les planches) — il reste à bord."
                         % _pieces(bord))
    return y


def _tableau(painter, page, y, bas, entetes, parts, lignes, num=(),
             pastilles=None, retrait=0.0):
    """Un tableau simple, borné à la page : la synthèse tient sur UNE feuille.

    Les en-têtes sont des couples (français, anglais) : le français en gras,
    l'anglais dessous en petit gris — le quai n'est pas toujours
    francophone. `pastilles` : une (couleur, hachuré) par ligne, dessinée
    dans un `retrait` laissé à gauche de la première colonne.

    Un chargement de cent lots ne doit pas repousser les planches de pont :
    on tronque en le DISANT — une ligne avalée sans un mot ferait croire au
    quai que le lot n'existe pas."""
    painter.setFont(QFont("Sans Serif", PT_TABLEAU))
    lh = painter.fontMetrics().lineSpacing()
    painter.setFont(QFont("Sans Serif", 7))
    lh_en = painter.fontMetrics().lineSpacing()
    h = lh + _mm(page, 0.6)
    h_tete = lh + lh_en + _mm(page, 0.6)
    place = max(1, int((bas - y - h_tete) / h) - 1)
    tronque = max(0, len(lignes) - place)
    if tronque:
        lignes = lignes[:place]
    largeur = page["largeur"] - retrait
    cols = [largeur * p for p in parts]
    xs, x = [], retrait
    for c in cols:
        xs.append(x)
        x += c
    # une marge DANS chaque cellule : un nombre calé à droite et le mot calé à
    # gauche de la colonne voisine se touchaient
    marge = _mm(page, 2)
    fin_trait = min(page["largeur"], xs[-1] + cols[-1])

    def cellule(i, y0, hauteur):
        return QRectF(xs[i] + marge, y0, cols[i] - 2 * marge, hauteur)

    painter.setPen(QPen(C_COUPLE, max(1.0, _mm(page, 0.2))))
    painter.drawLine(QPointF(0, y + h_tete), QPointF(fin_trait, y + h_tete))
    for i, t in enumerate(entetes):
        fr, en = (t, "") if isinstance(t, str) else t
        aligne = Qt.AlignmentFlag.AlignRight if i in num else Qt.AlignmentFlag.AlignLeft
        painter.setFont(QFont("Sans Serif", PT_TABLEAU, QFont.Weight.Bold))
        painter.setPen(C_TEXTE)
        painter.drawText(cellule(i, y, lh), aligne, fr)
        if en:
            painter.setFont(QFont("Sans Serif", 7))
            painter.setPen(C_GRIS)
            painter.drawText(cellule(i, y + lh, lh_en), aligne, en)
    y += h_tete
    painter.setFont(QFont("Sans Serif", PT_TABLEAU))
    for k, ligne in enumerate(lignes):
        if pastilles and k < len(pastilles):
            couleur, hachure = pastilles[k]
            _pastille(painter, page, _mm(page, 0.5), y + _mm(page, 0.7), couleur,
                      hachure=hachure)
        painter.setPen(C_TEXTE)
        for i, v in enumerate(ligne):
            painter.drawText(cellule(i, y, h),
                             Qt.AlignmentFlag.AlignRight if i in num
                             else Qt.AlignmentFlag.AlignLeft, str(v))
        y += h
    if tronque:
        painter.setPen(C_AXE)
        painter.drawText(QRectF(0, y, page["largeur"], h),
                         Qt.AlignmentFlag.AlignLeft,
                         "… et %d ligne(s) de plus : voir le manifeste exporté. "
                         "/ … and %d more: see the exported manifest." % (tronque, tronque))
        y += h
    return y


# ------------------------------------------------------------------ export
def nom_fichier(ctx):
    """« plan_chargement_MON_NAVIRE_point0001.pdf ».

    Le document se nomme par ce qu'il EST d'abord : sur le quai, la feuille
    change de mains et son nom doit se lire sans connaître la convention des
    exports du bord."""
    from .rapports import _sur
    return "plan_chargement_%s_point%04d.pdf" % (_sur(ctx.navire), ctx.point.numero)


def exporter(win, chemin, ctx=None):
    """Écrit le plan de chargement des dockers. Renvoie le chemin.

    Une page de synthèse, puis une page par cale chargée. Un chargement vide
    ne donne QUE la synthèse — et elle le dit."""
    os.makedirs(os.path.dirname(chemin) or ".", exist_ok=True)
    writer = QPdfWriter(chemin)
    _preparer(writer, ctx, win)
    peindre_sur(writer, win, ctx)
    return chemin


def _preparer(device, ctx, win):
    """A3 paysage, 300 dpi : la planche part sur le quai. Même réglage pour
    le PDF et pour l'aperçu avant impression (D-62)."""
    from . import rapports
    device.setPageSize(QPageSize(QPageSize.PageSizeId.A3))
    device.setPageOrientation(QPageLayout.Orientation.Landscape)
    device.setPageMargins(QMarginsF(12, 10, 12, 10), QPageLayout.Unit.Millimeter)
    if isinstance(device, QPdfWriter):
        device.setResolution(300)
        nav = (ctx or rapports.Contexte(win)).navire
        device.setTitle("Plan de chargement pour les dockers — %s" % nav)
        device.setCreator(MENTION)


def peindre_sur(device, win, ctx=None):
    """Peint le plan sur un périphérique déjà réglé. Rend le nombre de pages."""
    from . import rapports
    ctx = ctx or rapports.Contexte(win)
    plan = plan_du_bord(win)
    pages = cales_chargees(plan)
    lots = {m.lot_id: m for m in (win.condition.manifeste or [])}
    couples = list(getattr(win, "table_couples", None) or [])

    painter = QPainter(device)
    try:
        rect = device.pageLayout().paintRectPixels(device.resolution())
        page = {"largeur": rect.width(), "hauteur": rect.height(),
                "dpi": float(device.resolution())}
        n = 1 + len(pages)
        sous = "%s · imprimé le %s" % (ctx.point_texte, ctx.genere)
        haut, bas = _cadre(painter, page,
                           "PLAN DE CHARGEMENT — %s — synthèse" % ctx.navire,
                           sous, 1, n, ctx.navire)
        _page_synthese(painter, page, haut, bas, ctx, plan, lots)
        for i, (deck, contour, cales, cap, colis) in enumerate(pages):
            device.newPage()
            haut, bas = _cadre(painter, page,
                               "PLAN DE CHARGEMENT — %s — cale %s%s · %s"
                               % (ctx.navire, cap.code,
                                  " %s" % cap.name if cap.name else "", deck.name),
                               sous, i + 2, n, ctx.navire)
            h_leg = _hauteur_legende(page, painter, colis)
            dispo = QRectF(0, haut, page["largeur"],
                           max(_mm(page, 40), bas - haut - h_leg))
            pts = _points_de_la_cale(cap)
            ech, _P = _repere(page, dispo, pts)
            zone = _zone_utile(page, dispo, pts, ech)
            _dessiner_cale(painter, page, zone, ech, contour, cales, cap, colis,
                           couples, lots, ctx)
            _legende_cale(painter, page, zone.bottom() + _mm(page, 3),
                          deck, contour, cales, cap, colis, lots, ctx, ech)
        return n
    finally:
        painter.end()
