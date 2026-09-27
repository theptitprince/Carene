# -*- coding: utf-8 -*-
"""Transformation affine pixels <-> coordonnées navire, et petites géométries utiles."""
from __future__ import annotations

import math

import numpy as np


class Calibration:
    """Transformation affine 2D entre les pixels de l'image et le repère navire.

    real = M @ [u, v, 1]  avec M matrice 2x3.
    """

    def __init__(self, matrix=None):
        self._inv = None
        self.M = matrix

    # `M` passe par une propriété pour une seule raison : l'inverse mémorisée
    # (voir `_inverse`) doit être jetée dès que la matrice change, sinon un
    # recalage laisserait `to_pixel` répondre avec l'ancien calage.
    @property
    def M(self):
        return self._M

    @M.setter
    def M(self, matrix):
        self._M = np.asarray(matrix, dtype=float) if matrix is not None else None
        self._inv = None

    # ------------------------------------------------------------------ état
    @property
    def valid(self) -> bool:
        return self.M is not None and self.M.shape == (2, 3)

    def to_list(self):
        return self.M.tolist() if self.valid else None

    @classmethod
    def from_list(cls, data):
        return cls(np.asarray(data, float)) if data else cls()

    # ------------------------------------------------------------------ calage
    @staticmethod
    def fit(pixels, reals, isotrope=False) -> "Calibration":
        """Cale la transformation sur des couples (pixel, réel).

        - 2 points, `isotrope` : UNE échelle, axes à l'équerre, rotation
                      permise, image vue « v vers le bas = Y vers le haut ».
                      C'est le calage d'un plan VECTORIEL (PDF, DXF), qui n'a
                      par construction qu'une échelle : deux points sur la
                      ligne de foi — C.0 et C.60, ou PPAR et PPAV — suffisent,
                      et c'est ce qu'un humain sait cliquer (D-56) ;
        - 2 points, sinon : échelles indépendantes en u et v, sans rotation
                      (les 2 points doivent différer en u ET en v) — le calage
                      d'un scan, dont les deux sens peuvent être étirés ;
        - 3 points+ : affine complète par moindres carrés (absorbe la
                      rotation d'un scan légèrement de travers).
        """
        P = np.asarray(pixels, float)
        R = np.asarray(reals, float)
        n = len(P)
        if n < 2:
            raise ValueError("Au moins 2 points de référence sont nécessaires.")
        if n == 2 and isotrope:
            # x = a·u + b·v + c ; y = b·u − a·v + f  (similitude indirecte :
            # l'image a v vers le bas, le navire a Y vers le haut)
            A = []
            B = []
            for (u, v), (x, y) in zip(P, R):
                A.append([u, v, 1.0, 0.0])
                B.append(x)
                A.append([-v, u, 0.0, 1.0])
                B.append(y)
            (a, b, c, f), *_ = np.linalg.lstsq(np.asarray(A), np.asarray(B), rcond=None)
            if abs(a) < 1e-12 and abs(b) < 1e-12:
                raise ValueError("Les deux points de référence sont confondus : "
                                 "impossible de caler.")
            M = np.array([[a, b, c], [b, -a, f]])
        elif n == 2:
            du = P[1, 0] - P[0, 0]
            dv = P[1, 1] - P[0, 1]
            if abs(du) < 1e-9 or abs(dv) < 1e-9:
                raise ValueError(
                    "Avec 2 points seulement, ils doivent être décalés à la fois "
                    "horizontalement et verticalement sur l'image (par exemple : "
                    "PPAR sur la ligne de base, puis PPAV au niveau du pont). "
                    "Sinon, ajoutez un 3e point."
                )
            a = (R[1, 0] - R[0, 0]) / du
            e = (R[1, 1] - R[0, 1]) / dv
            c = R[0, 0] - a * P[0, 0]
            f = R[0, 1] - e * P[0, 1]
            M = np.array([[a, 0.0, c], [0.0, e, f]])
        else:
            A = np.hstack([P, np.ones((n, 1))])
            row_x, *_ = np.linalg.lstsq(A, R[:, 0], rcond=None)
            row_y, *_ = np.linalg.lstsq(A, R[:, 1], rcond=None)
            M = np.vstack([row_x, row_y])
        cal = Calibration(M)
        # transformation dégénérée ? (points alignés)
        if abs(np.linalg.det(M[:, :2])) < 1e-12:
            raise ValueError(
                "Points de référence dégénérés (alignés ?) : impossible de caler. "
                "Choisissez des points bien répartis sur le plan."
            )
        return cal

    def residuals(self, pixels, reals):
        """Écart (en mètres) entre les points réels donnés et les points recalculés."""
        errs = []
        for (u, v), (x, y) in zip(pixels, reals):
            xr, yr = self.to_real(u, v)
            errs.append(math.hypot(xr - x, yr - y))
        return errs

    def diagnostic(self):
        """Ce que la transformation dit du plan : (m/pixel selon u, m/pixel
        selon v, écart d'échelle en %, écart à l'équerre en degrés).

        Un plan est dessiné à une seule échelle et ses axes sont à angle
        droit : si le calage trouve deux échelles différentes ou des axes qui
        ne le sont plus, c'est qu'un point de référence est faux — l'affichage
        de ces chiffres évite d'apprendre la faute six mois plus tard sur une
        cale décalquée trop large."""
        a1 = self.M[:, 0]
        a2 = self.M[:, 1]
        s1 = float(math.hypot(*a1))
        s2 = float(math.hypot(*a2))
        aniso = abs(s1 - s2) / max(s1, s2, 1e-12) * 100.0
        cosang = float(np.dot(a1, a2)) / max(s1 * s2, 1e-12)
        cosang = max(-1.0, min(1.0, cosang))
        equerre = abs(90.0 - math.degrees(math.acos(cosang)))
        return s1, s2, aniso, equerre

    def avertissements(self, residus=None, seuil_residu=0.05):
        """Phrases en clair sur ce qui cloche (liste vide : rien à signaler)."""
        out = []
        if not self.valid:
            return ["Le plan n'est pas calé."]
        s1, s2, aniso, equerre = self.diagnostic()
        if aniso > 2.0:
            out.append(f"Les échelles selon les deux axes de l'image diffèrent "
                       f"de {aniso:.1f} % ({1/s1:.1f} et {1/s2:.1f} px/m) : "
                       "un plan a une seule échelle — vérifiez le point hors "
                       "axe, ou la coordonnée d'un point.")
        if equerre > 1.0:
            out.append(f"Les axes trouvés s'écartent de l'équerre de "
                       f"{equerre:.1f}° : un scan de travers tolère 1°, "
                       "au-delà un point est probablement faux.")
        if residus:
            pire = max(residus)
            if pire > seuil_residu:
                i = residus.index(pire) + 1
                out.append(f"Le point n°{i} s'écarte de {pire:.3f} m du "
                           "calage : il est mal placé ou sa coordonnée est "
                           "fausse.")
        return out

    # ------------------------------------------------------------------ application
    def to_real(self, u: float, v: float):
        x = self.M[0, 0] * u + self.M[0, 1] * v + self.M[0, 2]
        y = self.M[1, 0] * u + self.M[1, 1] * v + self.M[1, 2]
        return x, y

    def _inverse(self):
        """(A⁻¹, b) de la transformation, calculés une seule fois.

        `to_pixel` est appelée pour CHAQUE sommet à chaque redessin — plus de
        300 sur un pont du navire de référence, autant dans la vue iso, et à
        nouveau à chaque mouvement de souris pendant un glisser. Résoudre un système 2×2
        à chaque appel coûtait plus cher que le dessin lui-même."""
        if self._inv is None:
            self._inv = (np.linalg.inv(self._M[:, :2]), self._M[:, 2])
        return self._inv

    def to_pixel(self, x, y):
        """Pixels d'un point du repère navire.

        Accepte aussi des tableaux (x et y de même forme) : un contour entier
        se convertit alors d'un seul produit matriciel, au lieu d'un appel par
        sommet."""
        Ainv, b = self._inverse()
        if np.ndim(x) == 0 and np.ndim(y) == 0:
            dx, dy = x - b[0], y - b[1]
            return (float(Ainv[0, 0] * dx + Ainv[0, 1] * dy),
                    float(Ainv[1, 0] * dx + Ainv[1, 1] * dy))
        X = np.asarray(x, dtype=float)
        Y = np.asarray(y, dtype=float)
        U = Ainv @ np.stack([X.ravel() - b[0], Y.ravel() - b[1]])
        return U[0].reshape(X.shape), U[1].reshape(X.shape)


def clip_polygon_below(points, level):
    """Garde la partie du polygone dont la 2e coordonnée est <= level.

    Sutherland-Hodgman contre le demi-plan y <= level.
    `points` : liste de (x, y) en coordonnées réelles. Retourne une liste
    (éventuellement vide) de (x, y).
    """
    if not points:
        return []
    out = []
    n = len(points)
    for i in range(n):
        cur = points[i]
        nxt = points[(i + 1) % n]
        cur_in = cur[1] <= level
        nxt_in = nxt[1] <= level
        if cur_in:
            out.append(cur)
        if cur_in != nxt_in:
            # intersection avec y = level
            t = (level - cur[1]) / (nxt[1] - cur[1])
            out.append((cur[0] + t * (nxt[0] - cur[0]), level))
    return out


def aire_polygone(points) -> float:
    """Aire (m²) d'un polygone [(x, y), ...], quel que soit son sens."""
    pts = [(float(a), float(b)) for a, b in points]
    n = len(pts)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return abs(s) / 2.0


def intersection_polygones(a, b):
    """Les morceaux communs à deux polygones, du plus grand au plus petit.

    C'est ce qui permet de TRONQUER une zone décalquée au contour de sa cale
    (le bord : « les formes devraient être tronquées pour correspondre aux
    limites de la cale quand ça dépasse »). On s'appuie sur `QPainterPath` :
    Qt sait déjà découper deux contours quelconques — concaves, en L, à trous
    —, là où un Sutherland-Hodgman maison ne saurait que le convexe et
    rendrait des contours faux sur une cale en L. Rien de Qt ne remonte au
    modèle : on entre et on sort des listes de (x, y) du repère navire.

    Une intersection peut donner PLUSIEURS morceaux (une cale en U traversée
    par une bande) : ils sont tous rendus, triés par aire décroissante, et
    c'est à l'appelant de dire ce qu'il en garde.
    """
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath, QPolygonF

    def _chemin(points):
        path = QPainterPath()
        path.addPolygon(QPolygonF([QPointF(float(x), float(y))
                                   for x, y in points]))
        path.closeSubpath()
        return path

    if len(a) < 3 or len(b) < 3:
        return []
    morceaux = []
    # `simplified()` avant de sortir les polygones : sans lui, deux morceaux
    # disjoints (une bande qui traverse les deux bras d'une cale en U)
    # reviennent SOUDÉS par un couloir de largeur nulle — un contour que
    # personne ne saurait ni relire ni retoucher.
    inter = _chemin(a).intersected(_chemin(b)).simplified()
    for poly in inter.toFillPolygons():
        pts = [(float(p.x()), float(p.y())) for p in poly]
        # `toFillPolygons` referme chaque morceau : le dernier sommet répète
        # le premier. Un contour du modèle ne porte jamais deux fois le même
        # point — un sommet en double se verrait au premier glisser.
        if len(pts) >= 2 and math.hypot(pts[-1][0] - pts[0][0],
                                        pts[-1][1] - pts[0][1]) < 1e-9:
            pts.pop()
        if len(pts) >= 3:
            morceaux.append(pts)
    morceaux.sort(key=aire_polygone, reverse=True)
    return morceaux


def iso_project(x: float, y: float, z: float, scale: float = 10.0,
                angle_deg: float = 0.0):
    """Projection isométrique navire -> écran (Qt : v vers le bas).

    Le navire est vu **de dessus, par l'avant tribord** : X vers l'avant
    (droite-bas de l'écran), Y bâbord (droite-haut), Z vers le haut. Bâbord
    est donc du côté haut, comme sur le plan de pont vu de dessus — c'est ce
    qui permet de passer du plan à l'iso sans retourner la scène dans sa tête.

    Le repère du navire est direct (X avant, Y bâbord, Z haut) alors que la
    formule isométrique usuelle attend un axe transversal positif à TRIBORD.
    D'où le changement de signe ci-dessous : sans lui, l'image obtenue est le
    MIROIR du navire — un colis posé à bâbord y apparaît à tribord (D-25).

    `angle_deg` fait tourner la scène **autour de l'axe vertical** — on tourne
    autour du navire, on ne le bascule jamais : une vue de dessous ou de
    travers ne dirait rien de plus et perdrait le lecteur.
    """
    if angle_deg:
        import math
        a = math.radians(angle_deg)
        ca, sa = math.cos(a), math.sin(a)
        x, y = x * ca - y * sa, x * sa + y * ca
    t = -y                      # axe transversal compté positif vers tribord
    u = (x - t) * 0.8660 * scale
    v = ((x + t) * 0.5 - z) * scale
    return u, v


def polygon_centroid(points):
    """Centroïde approché (moyenne des sommets) d'un polygone [(x, y), ...]."""
    if not points:
        return (0.0, 0.0)
    return (sum(p[0] for p in points) / len(points),
            sum(p[1] for p in points) / len(points))


def point_in_polygon(x: float, y: float, points) -> bool:
    """Test d'appartenance point/polygone (ray casting). `points` : [(x,y), ...]."""
    n = len(points)
    if n < 3:
        return False
    inside = False
    x1, y1 = points[-1]
    for x2, y2 in points:
        if ((y1 > y) != (y2 > y)) and \
                (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-15) + x1):
            inside = not inside
        x1, y1 = x2, y2
    return inside


def nice_step(span: float, target: int = 10) -> float:
    """Pas « rond » (0.5, 1, 2, 5, 10...) donnant environ `target` divisions."""
    if span <= 0:
        return 1.0
    raw = span / target
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


# ---------------------------------------------------------- recouvrements
# Deux cales VOISINES d'un même pont se touchent bord à bord : c'est normal et
# voulu (une cloison n'a pas d'épaisseur sur un décalque, et les sommets
# s'accrochent l'un sur l'autre). Ce qui n'est pas voulu, c'est qu'elles se
# MORDENT : un colis posé dans la zone commune serait compté deux fois, et la
# cale « du dessous » devient impossible à viser au clic.
#
# La frontière entre les deux se mesure en PROFONDEUR, pas en aire : deux
# cales jointives partagent une arête de 12 m, un demi-millimètre de bavure
# donne déjà 6 000 mm² — alors qu'un vrai recouvrement de 20 cm sur 1 m de
# large en donne 200 000 sans être plus grave. On garde donc une tolérance
# exprimée en mètres, que le bord peut lire sur son plan.
TOLERANCE_RECOUVREMENT_M = 0.005      # 5 mm : l'épaisseur d'un trait de plan


def profondeur_recouvrement(a, b) -> float:
    """De combien de mètres ces deux polygones se mordent-ils (0 = pas du tout).

    On prend l'intersection (`intersection_polygones`, qui sait le concave et
    les morceaux multiples) et on ramène chaque morceau à une ÉPAISSEUR : la
    largeur du RECTANGLE de même aire et même périmètre. Deux cales qui se
    chevauchent donnent justement une bande, et le nombre rendu est alors
    exactement la largeur que le bord lit sur son plan (20 cm de recouvrement
    → 0,20 m). Quand la tache n'a rien d'un rectangle (le discriminant
    devient négatif), on retombe sur 2 × aire / périmètre, qui donne le bon
    ordre de grandeur.

    C'est bien une épaisseur qu'on mesure, pas une aire : deux cales jointives
    partagent une arête de 12 m, où un demi-millimètre de bavure ferait déjà
    6 000 mm² — autant qu'un vrai recouvrement, en bien moins grave.
    """
    if len(a) < 3 or len(b) < 3:
        return 0.0
    # pré-tri par rectangles englobants : sur un pont de dix cales, la plupart
    # des paires sont loin l'une de l'autre et n'ont pas à réveiller Qt
    ax = [p[0] for p in a]
    ay = [p[1] for p in a]
    bx = [p[0] for p in b]
    by = [p[1] for p in b]
    if min(ax) > max(bx) or min(bx) > max(ax) \
            or min(ay) > max(by) or min(by) > max(ay):
        return 0.0
    pire = 0.0
    for morceau in intersection_polygones(a, b):
        aire = aire_polygone(morceau)
        n = len(morceau)
        perim = sum(math.hypot(morceau[(i + 1) % n][0] - morceau[i][0],
                               morceau[(i + 1) % n][1] - morceau[i][1])
                    for i in range(n))
        if perim <= 1e-12:
            continue
        disc = perim * perim / 4.0 - 4.0 * aire
        if disc >= 0.0:
            largeur = (perim / 2.0 - math.sqrt(disc)) / 2.0
        else:
            largeur = 2.0 * aire / perim
        pire = max(pire, largeur)
    return pire
