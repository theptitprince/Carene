# -*- coding: utf-8 -*-
"""Scènes graphiques : plan calé (profil ou pont) avec grille, repères et objets.

Ce module porte aussi ce qui, du côté Qt, est commun à toutes les vues de
plan : d'où viennent les traits accrochables (PDF ou DXF — voir
`source_traits`) et leur **lecture en fil de fond** (`ChargeurTraits`). Le plan
d'ensemble du navire de référence demande 2 à 8 s de lecture : la faire dans le fil de
l'interface fige la fenêtre juste au moment où l'on commence à décalquer.
"""
from __future__ import annotations

import math

from PySide6.QtCore import (
    QCoreApplication,
    QLineF,
    QObject,
    QPointF,
    QRunnable,
    Qt,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import QBrush, QColor, QFont, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

import os

import numpy as np

from . import theme
from .geometry import nice_step
from .items import (
    AnnotationItem,
    CalMarkerItem,
    DeckCapacityItem,
    DeckLineItem,
    EpontilleItem,
    ObstacleItem,
    ProfileCapacityItem,
    SnapMarkerItem,
    ZoneChargeItem,
)

# Les calques du décalquage, dans l'ordre où ils s'empilent. Décalquer un
# contour de cale sur un plan de chantier chargé est impossible si tout est dessiné
# en même temps : chacun s'éteint séparément.
CALQUES = ("fond", "cales", "zones", "obstacles", "epontilles", "info",
           "construction", "grille")
NOMS_CALQUES = {
    "fond": "Fond de plan",
    "cales": "Cales et contours tracés",
    "zones": "Zones de charge",
    "obstacles": "Zones interdites / hauteur",
    "epontilles": "Épontilles amovibles",
    "info": "Informations (non contraignant)",
    "construction": "Traits de construction",
    "grille": "Grille du repère",
}
from .pdf_plan import SnapIndex, snap as _snap_parmi

# Rayon d'accroche, en pixels d'ÉCRAN (D-24). Il est ici, et pas dans chaque
# fenêtre : deux valeurs pour le même geste, ce serait deux accroches
# différentes d'un écran à l'autre.
SNAP_PX = 8.0

# Un plan A0 rendu à 200 dpi pèse 60 millions de pixels : le relire du disque
# à chaque rafraîchissement (chaque sommet déplacé) prendrait des secondes.
# On garde les derniers pixmaps chargés, repérés par chemin et date.
_PIXMAPS = {}
_PIXMAPS_MAX = 4


def pixmap_for(path: str) -> QPixmap:
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return QPixmap()
    cle = (os.path.abspath(path), mtime)
    pm = _PIXMAPS.get(cle)
    if pm is None:
        pm = QPixmap(path)
        if not pm.isNull():
            while len(_PIXMAPS) >= _PIXMAPS_MAX:
                _PIXMAPS.pop(next(iter(_PIXMAPS)))
            _PIXMAPS[cle] = pm
    return pm


def ensure_rendered(calibrated) -> bool:
    """Si l'image d'un plan venu d'un PDF ou d'un DXF a disparu (dossier copié
    sans ses rendus, nettoyage…), on la refait depuis le fichier d'origine avec
    les mêmes réglages — page/rotation/dpi pour un PDF, calques/origine/
    résolution pour un DXF : les pixels retombent exactement au même endroit,
    le calage et les tracés restent bons. Renvoie True si l'image existe."""
    if not calibrated or not calibrated.image_path:
        return False
    if os.path.exists(calibrated.image_path):
        return True
    dxf = getattr(calibrated, "dxf_path", "")
    if dxf and os.path.exists(dxf):
        try:
            from . import dxf_plan
            dessin = dxf_plan.dessin_pour(dxf)
            w, h = calibrated.dxf_size
            if w and h:
                # cadre imposé : les pixels retombent exactement au même
                # endroit, donc le calage et les tracés restent bons
                dxf_plan.rendre_cadre(dessin, calibrated.image_path,
                                      calibrated.dxf_calques,
                                      calibrated.dxf_origin,
                                      calibrated.dxf_resolution, w, h)
            else:
                dxf_plan.rendre(dessin, calibrated.image_path,
                                calques=calibrated.dxf_calques,
                                resolution=calibrated.dxf_resolution)
        except Exception:
            return False
        return os.path.exists(calibrated.image_path)
    if not calibrated.pdf_path or not os.path.exists(calibrated.pdf_path):
        return False
    try:
        from . import pdf_plan
        pdf_plan.render_page(calibrated.pdf_path, calibrated.pdf_page,
                             calibrated.pdf_rotation, calibrated.pdf_dpi,
                             calibrated.image_path)
    except Exception:
        return False
    return os.path.exists(calibrated.image_path)


# --------------------------------------------------- traits accrochables
def source_traits(calibrated):
    """(module, arguments, clé de cache) des traits accrochables d'une vue,
    ou None si son fond n'est pas vectoriel.

    `pdf_plan` et `dxf_plan` offrent la **même façade** — `extract_vertices`,
    `snap_index_for`, `snap_index_cached`, `cle_cache`, `ranger_index` — et
    c'est ici, à un seul endroit, qu'on choisit laquelle : tout le reste de
    l'interface manipule un index d'accroche sans savoir d'où il sort."""
    if calibrated is None:
        return None
    dxf = getattr(calibrated, "dxf_path", "")
    pdf = getattr(calibrated, "pdf_path", "")
    # Le fichier de sommets rangé avec le navire (`traits_plan`) passe AVANT
    # la source : il est là même quand le PDF du chantier n'a pas voyagé avec
    # le dossier, et il se lit en une fraction de seconde au lieu de plusieurs.
    from . import traits_plan
    image = getattr(calibrated, "image_path", "")
    if image and traits_plan.existe(image) and not (
            (dxf and os.path.exists(dxf)) or (pdf and os.path.exists(pdf))):
        chemin = traits_plan.chemin_traits(image)
        return traits_plan, (chemin,), traits_plan.cle_cache(chemin)
    if dxf:
        from . import dxf_plan
        args = (dxf, calibrated.dxf_calques,
                tuple(calibrated.dxf_origin), float(calibrated.dxf_resolution))
        return dxf_plan, args, dxf_plan.cle_cache(*args)
    if pdf:
        from . import pdf_plan
        args = (pdf, calibrated.pdf_page,
                calibrated.pdf_rotation, calibrated.pdf_dpi)
        return pdf_plan, args, pdf_plan.cle_cache(*args)
    if image and traits_plan.existe(image):
        chemin = traits_plan.chemin_traits(image)
        return traits_plan, (chemin,), traits_plan.cle_cache(chemin)
    return None


def index_traits(calibrated):
    """L'index d'accroche des traits **s'il est déjà prêt**, sans rien lire.

    Jamais un index à moitié construit : `ranger_index` n'est appelé qu'une
    fois le `SnapIndex` entièrement bâti, dans le fil de l'interface."""
    src = source_traits(calibrated)
    if src is None:
        return None
    module, args, _ = src
    try:
        return module.snap_index_cached(*args)
    except Exception:
        return None


class _TacheTraits(QRunnable):
    """Lecture des sommets d'un plan, hors du fil de l'interface."""

    def __init__(self, chargeur, module, args, cle, image_path=""):
        super().__init__()
        self._chargeur = chargeur
        self._module = module
        self._args = args
        self._cle = cle
        self._image = image_path
        self.setAutoDelete(True)

    def run(self):
        try:
            points = self._module.extract_vertices(*self._args)
            index = SnapIndex(points)
        except Exception as e:      # plan illisible : on le dira, sans figer
            self._prevenir(self._chargeur._echoue, self._cle, str(e))
            return
        # Les sommets partent avec le navire (`traits_plan`) : la prochaine
        # ouverture, ici ou à bord sans le PDF, les retrouvera sans relire.
        from . import traits_plan
        if self._image and self._module is not traits_plan \
                and not traits_plan.existe(self._image):
            traits_plan.sauver(self._image, points)
        # l'index part fini vers le fil de l'interface, qui seul le range :
        # personne ne peut donc en attraper un à moitié construit
        self._prevenir(self._chargeur._fini, self._cle, index)

    @staticmethod
    def _prevenir(signal, *args):
        # l'application peut fermer pendant la lecture : le destinataire du
        # signal n'existe alors plus, et ce n'est pas une erreur
        try:
            signal.emit(*args)
        except RuntimeError:
            pass


class ChargeurTraits(QObject):
    """Lecture des traits d'un fond de plan en tâche de fond.

    Tant que la lecture n'est pas finie, `index(...)` renvoie None : l'accroche
    est simplement absente, et l'appelant affiche « lecture des traits… ».
    Rien n'attend, rien ne fige, et il n'existe à aucun instant d'index
    partiel — le `SnapIndex` n'est rangé dans le cache de session qu'une fois
    entièrement bâti, et depuis le fil de l'interface."""

    pret = Signal(object)          # clé de cache : un index vient d'être rangé
    echec = Signal(object, str)    # clé de cache, message
    _fini = Signal(object, object)
    _echoue = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._en_cours = {}        # clé → (module, args)
        self._rates = {}           # clé → message (on ne réessaie pas en boucle)
        self._pool = QThreadPool.globalInstance()
        self._fini.connect(self._ranger)
        self._echoue.connect(self._rater)
        app = QCoreApplication.instance()
        if app is not None:
            # à la fermeture on laisse les lectures finir un court instant,
            # plutôt que de détruire l'objet sous les pieds d'un fil
            app.aboutToQuit.connect(lambda: self._pool.waitForDone(3000))

    # -- interrogation
    def index(self, calibrated):
        """L'index prêt, ou None (absent ou encore en lecture)."""
        return index_traits(calibrated)

    def en_lecture(self, calibrated) -> bool:
        src = source_traits(calibrated)
        return src is not None and src[2] in self._en_cours

    def echec_de(self, calibrated):
        src = source_traits(calibrated)
        return None if src is None else self._rates.get(src[2])

    # -- demande
    def demander(self, calibrated):
        """Lance la lecture si besoin. Renvoie l'index s'il est déjà prêt,
        None sinon — l'appelant continue sans accroche et sera prévenu par
        `pret`."""
        src = source_traits(calibrated)
        if src is None:
            return None
        module, args, cle = src
        idx = module.snap_index_cached(*args)
        if idx is not None:
            return idx
        if cle in self._en_cours or cle in self._rates:
            return None
        chemin = args[0]
        if not chemin or not os.path.exists(chemin):
            self._rates[cle] = f"fichier introuvable ({chemin})"
            return None
        self._en_cours[cle] = (module, args)
        self._pool.start(_TacheTraits(self, module, args, cle,
                                      getattr(calibrated, "image_path", "")))
        return None

    def oublier_echecs(self):
        self._rates.clear()

    def attendre(self, ms: int = 30000) -> bool:
        """Attend la fin des lectures en cours — pour les tests et pour une
        fermeture propre. L'interface, elle, n'appelle jamais ceci."""
        fini = self._pool.waitForDone(int(ms))
        # les index reviennent par signal : il faut laisser le fil de
        # l'interface les ranger avant de dire que c'est fini
        app = QCoreApplication.instance()
        if app is not None:
            app.processEvents()
        return fini

    def attendre_index(self, calibrated, ms: int = 30000):
        """Lit les traits **en attendant** qu'ils le soient, et rend l'index.

        Réservé aux scripts et aux tests qui veulent l'accroche tout de suite :
        l'interface, elle, ne bloque jamais (voir `demander`)."""
        idx = self.demander(calibrated)
        if idx is not None:
            return idx
        if self.en_lecture(calibrated):
            self.attendre(ms)
        return self.index(calibrated)

    # -- retour dans le fil de l'interface
    def _ranger(self, cle, index):
        module_args = self._en_cours.pop(cle, None)
        if module_args is not None:
            module_args[0].ranger_index(cle, index)
        self.pret.emit(cle)

    def _rater(self, cle, message):
        self._en_cours.pop(cle, None)
        self._rates[cle] = message
        self.echec.emit(cle, message)


_CHARGEUR = None


def chargeur() -> ChargeurTraits:
    """Le lecteur de traits de la session (un seul pour toute l'application :
    deux fenêtres ouvertes sur le même plan ne le lisent pas deux fois)."""
    global _CHARGEUR
    if _CHARGEUR is None:
        _CHARGEUR = ChargeurTraits()
    return _CHARGEUR


def lignes_de_construction(calibrated, rect):
    """Les traits de construction d'un plan, en pixels : [((x1,y1),(x2,y2))].

    Décalquer un contour sur un plan de chantier, c'est s'appuyer sur des
    droites — la ligne de foi, un couple, une cote reportée au compas — pas
    dessiner à main levée. Chaque trait est une **valeur constante sur un axe**
    du repère navire ; il traverse tout le plan. Un trait dont l'axe n'est pas
    celui du plan (un Y sur un profil) est ignoré, il ne veut rien dire là.

    Renvoie aussi le libellé de chacun : [(p1, p2, libellé)]."""
    traits = list(getattr(calibrated, "traits", None) or [])
    cal = getattr(calibrated, "calibration", None)
    if not traits or cal is None or not cal.valid or rect is None:
        return []
    coins = [cal.to_real(rect.left(), rect.top()),
             cal.to_real(rect.right(), rect.top()),
             cal.to_real(rect.right(), rect.bottom()),
             cal.to_real(rect.left(), rect.bottom())]
    a1 = [c[0] for c in coins]
    a2 = [c[1] for c in coins]
    axes = tuple(calibrated.axes)
    bornes = {axes[0]: (min(a1), max(a1)), axes[1]: (min(a2), max(a2))}
    out = []
    for t in traits:
        axe = str(t.get("axe") or "")
        if axe not in bornes:
            continue
        autre = axes[1] if axe == axes[0] else axes[0]
        v = float(t.get("valeur", 0.0))
        lo, hi = bornes[autre]
        if axe == axes[0]:
            p1, p2 = cal.to_pixel(v, lo), cal.to_pixel(v, hi)
        else:
            p1, p2 = cal.to_pixel(lo, v), cal.to_pixel(hi, v)
        out.append(((p1[0], p1[1]), (p2[0], p2[1]),
                    t.get("libelle") or f"{axe} = {v:g} m"))
    return out


def groupe_de_construction(calibrated, rect):
    """(groupe graphique, lignes) — le dessin des traits de construction."""
    lignes = lignes_de_construction(calibrated, rect)
    if not lignes:
        return None, []
    group = QGraphicsItemGroup()
    pen = QPen(QColor(theme.TRAIT_CONSTRUCTION), 0)
    pen.setCosmetic(True)
    pen.setStyle(Qt.PenStyle.DashDotLine)
    font = QFont()
    font.setPointSizeF(8.0)
    for p1, p2, libelle in lignes:
        line = QGraphicsLineItem(p1[0], p1[1], p2[0], p2[1])
        line.setPen(pen)
        group.addToGroup(line)
        txt = QGraphicsSimpleTextItem(libelle)
        txt.setFont(font)
        txt.setBrush(QBrush(QColor(theme.TRAIT_CONSTRUCTION)))
        txt.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        txt.setPos(p1[0], p1[1])
        group.addToGroup(txt)
    return group, [(p1, p2) for p1, p2, _l in lignes]


def accrocher_construction(lignes, x, y, radius):
    """Accroche aux traits de construction : (point, force) ou None.

    Force 2 pour une intersection de deux traits — c'est un point, aussi sûr
    qu'un sommet ; force 1 pour la projection sur un seul trait, qui ne
    contraint qu'une coordonnée et ne doit donc jamais l'emporter sur un
    sommet réel du plan."""
    lignes = lignes or []
    if not lignes or radius <= 0:
        return None
    proj = []
    for (ax, ay), (bx, by) in lignes:
        dx, dy = bx - ax, by - ay
        n2 = dx * dx + dy * dy
        if n2 <= 1e-12:
            continue
        t = ((x - ax) * dx + (y - ay) * dy) / n2
        px, py = ax + t * dx, ay + t * dy
        d = ((px - x) ** 2 + (py - y) ** 2) ** 0.5
        if d <= radius:
            proj.append((d, px, py, (ax, ay, dx, dy)))
    if not proj:
        return None
    best = None
    for i in range(len(proj)):
        for j in range(i + 1, len(proj)):
            ax, ay, dx, dy = proj[i][3]
            cx, cy, ex, ey = proj[j][3]
            den = dx * ey - dy * ex
            if abs(den) < 1e-9:
                continue
            t = ((cx - ax) * ey - (cy - ay) * ex) / den
            ix, iy = ax + t * dx, ay + t * dy
            d = ((ix - x) ** 2 + (iy - y) ** 2) ** 0.5
            if d <= radius and (best is None or d < best[0]):
                best = (d, ix, iy)
    if best is not None:
        return (best[1], best[2]), 2
    proj.sort(key=lambda p: p[0])
    return (proj[0][1], proj[0][2]), 1


def index_local(calibrated, polygones=(), exclure=None):
    """Index d'accroche des points PROPRES à une vue : les points de calage
    déjà posés, et les contours déjà tracés dessus.

    `polygones` : des suites de (x, y) en coordonnées navire — un bord de cale
    s'aligne sur la cloison voisine, un point de calage se reprend sans le
    rechercher. `exclure` : (la liste de points, l'indice) du sommet qu'on est
    en train de tirer, comparé par IDENTITÉ de liste.

    Partagé par la scène de décalquage et la fiche de plan de cale : deux
    copies de cette liste, ce serait un jour deux accroches différentes."""
    pts = []
    if calibrated is None:
        return SnapIndex(np.zeros((0, 2)), cell=128.0)
    for cp in calibrated.cal_points:
        pts.append(tuple(cp["pixel"]))
    cal = calibrated.calibration
    if cal.valid:
        for poly in polygones:
            gardes = [p for i, p in enumerate(poly)
                      if not (exclure is not None and poly is exclure[0]
                              and i == exclure[1])]
            if not gardes:
                continue
            # d'un seul produit matriciel : un pont du navire de référence
            # porte 313 sommets, et cet index se rebâtit à chaque retouche
            P = np.asarray(gardes, dtype=float)
            u, v = cal.to_pixel(P[:, 0], P[:, 1])
            pts.extend(zip(u.tolist(), v.tolist()))
    return SnapIndex(np.asarray(pts, dtype=float).reshape(-1, 2), cell=128.0)


def accrocher(point, rayon, indexes, lignes=(), exclude=None):
    """Le point d'accroche retenu : (QPointF, accroché ?).

    Le sommet le plus proche à moins de `rayon`, parmi les index donnés
    (traits du fond vectoriel, tracés, points de calage) ; `exclude` écarte un
    pixel précis — le sommet qu'on déplace. Les traits de construction
    ensuite : leur INTERSECTION vaut un sommet (c'est un point) et peut
    l'emporter, tandis que la simple projection sur un seul trait ne contraint
    qu'une coordonnée et ne l'emporte donc jamais sur un sommet réel du plan.

    Partagé par le décalquage et la fiche de plan de cale : c'est LE geste de
    l'application (D-24), il ne doit pas exister en deux exemplaires."""
    x, y = point.x(), point.y()
    hit = _snap_parmi(x, y, rayon, indexes, exclude=exclude)
    cons = accrocher_construction(lignes, x, y, rayon)
    if cons is not None:
        (cx, cy), force = cons
        d_cons = math.hypot(cx - x, cy - y)
        if hit is None:
            return QPointF(cx, cy), True
        d_hit = math.hypot(hit[0] - x, hit[1] - y)
        if force == 2 and d_cons < d_hit:
            return QPointF(cx, cy), True
    if hit is None:
        return point, False
    return QPointF(hit[0], hit[1]), True


class VuePlanBase(QGraphicsView):
    """Ce que toutes les vues de plan partagent : le zoom molette AU CURSEUR
    et le déplacement au bouton du milieu.

    La fenêtre de décalquage (`plan_editor.PlanGraphicsView`) et la fiche de
    plan de cale (`cale_image._ImageView`) en héritent : on ne réapprend pas
    la souris d'un écran à l'autre, et une correction du zoom vaut pour les
    deux d'un coup."""

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self._panning = False
        self._pan_start = None

    def view_scale(self) -> float:
        """Pixels d'écran par pixel d'image — c'est ce qui garde le rayon
        d'accroche à SNAP_PX pixels d'ÉCRAN quel que soit le zoom."""
        t = self.transform()
        return math.sqrt(abs(t.m11() * t.m22() - t.m12() * t.m21())) or 1.0

    def scene_pos(self, event) -> QPointF:
        return self.mapToScene(event.position().toPoint())

    def wheelEvent(self, event):
        """Zoom au curseur : le point visé reste sous la souris.

        L'ancre AnchorUnderMouse de Qt ne s'applique que si le widget est
        réellement sous le pointeur physique (elle relit QCursor::pos()) —
        elle rate donc la tablette, le zoom pendant un tracé, et toute
        simulation. On recale nous-mêmes : c'est deux lignes et c'est exact."""
        vue_px = event.position().toPoint()
        avant = self.mapToScene(vue_px)
        ancre = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        f = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(f, f)
        d = self.mapToScene(vue_px) - avant
        self.translate(d.x(), d.y())
        self.setTransformationAnchor(ancre)
        event.accept()

    @property
    def panning(self) -> bool:
        return self._panning

    def _pan_move(self, event) -> bool:
        """Un déplacement est en cours : fait défiler la vue. True s'il a
        consommé l'événement."""
        if not self._panning:
            return False
        d = event.position() - self._pan_start
        self._pan_start = event.position()
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value() - int(d.x()))
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() - int(d.y()))
        event.accept()
        return True


class PlanScene(QGraphicsScene):
    """Scène d'un plan calé. kind = "profil" (X-Z) ou "pont" (X-Y)."""

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setBackgroundBrush(QBrush(QColor(theme.BG_DEEP)))
        self.calibrated = None      # Calibrated courant
        self.project = None         # Project (pour le profil : ponts + projections)
        self.deck = None            # Deck courant (vue pont)
        self.pixmap_item = None
        self.grid_group = None
        self.grid_visible = True
        self.cal_markers = []
        self.object_items = []      # capacités / lignes de ponts
        self.zone_items = []        # zones de charge admissible (calque)
        self.obstacle_items = []    # zones interdites / à hauteur réduite
        self.epontille_items = []   # emplacements d'épontilles amovibles
        self.annotation_items = []  # calque d'information du pont (Deck.annotations)
        self.construction_group = None   # traits de construction du décalquage
        self.construction_lines = []     # les mêmes, en pixels, pour l'accroche
        self.snap_marker = None
        # état des calques : conservé d'un plan à l'autre, c'est un réglage
        # de travail, pas une propriété du plan
        self.layers = {k: True for k in CALQUES}

    # ------------------------------------------------------------------ chargement
    def load(self, calibrated, project=None, deck=None) -> bool:
        # Les listes d'objets sont vidées AVANT `clear()`, et la scène se
        # tait pendant : détruire un objet sélectionné émet selectionChanged
        # au milieu de la destruction, et le gestionnaire de l'éditeur
        # repassait alors sur `object_items` — des objets déjà détruits côté
        # C++ (« Internal C++ object already deleted », vu à bord).
        self.object_items = []
        self.zone_items = []
        self.obstacle_items = []
        self.epontille_items = []
        self.annotation_items = []
        self.blockSignals(True)
        try:
            self.clear()
        finally:
            self.blockSignals(False)
        self.pixmap_item = None
        self.grid_group = None
        self.cal_markers = []
        self.object_items = []
        self.zone_items = []
        self.obstacle_items = []
        self.epontille_items = []
        self.annotation_items = []
        self.construction_group = None
        self.construction_lines = []
        self.snap_marker = None
        self.calibrated = calibrated
        self.project = project
        self.deck = deck
        if not calibrated or not calibrated.image_path:
            return False
        ensure_rendered(calibrated)
        pm = pixmap_for(calibrated.image_path)
        if pm.isNull():
            return False
        self.pixmap_item = QGraphicsPixmapItem(pm)
        self.pixmap_item.setZValue(0)
        self.pixmap_item.setVisible(self.layers["fond"])
        self.addItem(self.pixmap_item)
        self.setSceneRect(self.pixmap_item.boundingRect().adjusted(-80, -80, 80, 80))
        for i, cp in enumerate(calibrated.cal_points, start=1):
            self._add_marker(i, QPointF(*cp["pixel"]),
                             cp.get("label", ""), cp.get("real"))
        if calibrated.calibration.valid:
            self.rebuild_overlays()
        self.snap_marker = SnapMarkerItem()
        self.addItem(self.snap_marker)
        self.apply_layers()
        return True

    # ------------------------------------------------------------------ accroche
    def show_snap(self, pos):
        """Montre le repère d'accroche en `pos` (QPointF), ou le cache (None)."""
        if self.snap_marker is None:
            return
        if pos is None:
            self.snap_marker.setVisible(False)
        else:
            self.snap_marker.setPos(pos)
            self.snap_marker.setVisible(True)

    def local_snap_index(self, exclude_capacity=None, exclude_vertex=None):
        """Index d'accroche des sommets déjà tracés sur cette vue (polygones
        des capacités, contour de pont) et des points de calage — voir
        `index_local`, que partage aussi la fiche de plan de cale."""
        polygones = []
        if self.kind == "pont" and self.deck is not None:
            polygones = [cap.points for cap in self.deck.capacities]
        exclure = None
        if exclude_capacity is not None and exclude_vertex is not None:
            exclure = (exclude_capacity.points, exclude_vertex)
        return index_local(self.calibrated, polygones, exclure)

    # ------------------------------------------------------------------ calage
    def _add_marker(self, index, pos, label="", coords=None):
        m = CalMarkerItem(index, label, coords)
        m.setPos(pos)
        m.setZValue(30)
        self.addItem(m)
        self.cal_markers.append(m)

    def add_cal_point(self, pixel: QPointF, real, label=""):
        self.calibrated.cal_points.append(
            {"pixel": [pixel.x(), pixel.y()], "real": list(real), "label": label}
        )
        self._add_marker(len(self.calibrated.cal_points), pixel, label, real)

    def clear_cal_points(self):
        for m in self.cal_markers:
            self.removeItem(m)
        self.cal_markers = []
        self.calibrated.cal_points = []

    # ------------------------------------------------------------------ couches
    def visible_x_range(self):
        """Étendue X couverte par l'image (pour tracer les lignes de ponts)."""
        cal = self.calibrated.calibration
        rect = self.pixmap_item.boundingRect()
        xs = [cal.to_real(rect.left(), rect.top())[0],
              cal.to_real(rect.right(), rect.bottom())[0],
              cal.to_real(rect.left(), rect.bottom())[0],
              cal.to_real(rect.right(), rect.top())[0]]
        return min(xs), max(xs)

    def rebuild_overlays(self):
        if self.grid_group is not None:
            self.removeItem(self.grid_group)
            self.grid_group = None
        if self.construction_group is not None:
            self.removeItem(self.construction_group)
            self.construction_group = None
        vieux = (self.object_items + self.zone_items + self.obstacle_items
                 + self.epontille_items + self.annotation_items)
        self.object_items = []
        self.zone_items = []
        self.obstacle_items = []
        self.epontille_items = []
        self.annotation_items = []
        # même raison que dans `load` : retirer un objet sélectionné émet
        # selectionChanged, et le gestionnaire ne doit pas retrouver dans les
        # listes des objets en cours de destruction
        self.blockSignals(True)
        try:
            for it in vieux:
                self.removeItem(it)
        finally:
            self.blockSignals(False)
        if self.pixmap_item is None or not self.calibrated.calibration.valid:
            return
        self.grid_group = self._build_grid()
        self.grid_group.setZValue(10)
        self.grid_group.setVisible(self.grid_visible)
        self.addItem(self.grid_group)
        self.construction_group = self._build_construction()
        if self.construction_group is not None:
            # au-dessus de la grille et du fond, sous les tracés : on décalque
            # EN SUIVANT ces traits, il faut les voir sans qu'ils masquent
            self.construction_group.setZValue(12)
            self.construction_group.setVisible(self.layers.get("construction", True))
            self.addItem(self.construction_group)
        cal = self.calibrated.calibration
        if self.kind == "profil" and self.project is not None:
            xr = self.visible_x_range()
            for deck in self.project.sorted_decks():
                it = DeckLineItem(deck, cal, xr)
                it.setZValue(15)
                self.addItem(it)
                self.object_items.append(it)
                for capa in deck.capacities:
                    if capa.kind == "CONTOUR" or not capa.points:
                        continue
                    pit = ProfileCapacityItem(capa, cal)
                    pit.setZValue(20)
                    self.addItem(pit)
                    self.object_items.append(pit)
        elif self.kind == "pont" and self.deck is not None:
            for capa in self.deck.capacities:
                it = DeckCapacityItem(capa, cal)
                # `Z_NORMAL` : la cale sélectionnée, elle, monte d'elle-même
                # au-dessus des autres (voir DeckCapacityItem.itemChange)
                it.setZValue(DeckCapacityItem.Z_NORMAL)
                self.addItem(it)
                self.object_items.append(it)
                for zone in getattr(capa, "zones_charge", None) or []:
                    if len(zone.get("points") or []) < 3:
                        continue
                    zi = ZoneChargeItem(zone, cal, capa)
                    zi.setZValue(17)
                    self.addItem(zi)
                    self.zone_items.append(zi)
                for obs in getattr(capa, "obstacles", None) or []:
                    if len(obs) < 4:
                        continue
                    oi = ObstacleItem(obs, cal, capa)
                    oi.setZValue(18)
                    self.addItem(oi)
                    self.obstacle_items.append(oi)
                for ep in getattr(capa, "epontilles", None) or []:
                    ei = EpontilleItem(ep, capa, cal)
                    ei.setZValue(19)
                    self.addItem(ei)
                    self.epontille_items.append(ei)
            # Le calque d'information appartient au PONT, pas à une cale : une
            # clé de saisissage se trouve aussi bien sur le platelage entre
            # deux cales. Il se dessine au-dessus de tout ce qui contraint,
            # puisqu'il ne contraint rien et qu'on doit pouvoir le lire.
            for note in getattr(self.deck, "annotations", None) or []:
                if not (note.get("points") or []):
                    continue
                ai = AnnotationItem(note, cal, self.deck)
                ai.setZValue(21)
                self.addItem(ai)
                self.annotation_items.append(ai)
        self.apply_layers()

    def item_for_epontille(self, epontille):
        """L'objet graphique de CETTE épontille (identité, pas identifiant :
        c'est le dictionnaire du navire qu'on manipule)."""
        for it in self.epontille_items:
            if it.epontille is epontille:
                return it
        return None

    def item_for_capacity(self, capacity):
        for it in self.object_items:
            if getattr(it, "capacity", None) is capacity:
                return it
        return None

    def item_for_zone(self, zone):
        """L'objet graphique de CETTE zone de charge (identité : c'est le
        dictionnaire du navire qu'on manipule, pas une copie)."""
        return next((it for it in self.zone_items if it.zone is zone), None)

    def item_for_obstacle(self, obstacle):
        """L'objet graphique de CETTE zone interdite ou à hauteur réduite.

        La comparaison se fait sur `source`, la liste du modèle : `obstacle`
        n'est qu'une copie de travail (voir `ObstacleItem`)."""
        return next((it for it in self.obstacle_items
                     if getattr(it, "source", None) is obstacle), None)

    def item_for_annotation(self, note):
        """L'objet graphique de CETTE annotation du calque d'information."""
        return next((it for it in self.annotation_items
                     if it.annotation is note), None)

    def set_grid_visible(self, visible: bool):
        self.grid_visible = visible
        self.layers["grille"] = bool(visible)
        if self.grid_group is not None:
            self.grid_group.setVisible(visible)

    # ------------------------------------------------------------------ calques
    def set_layer_visible(self, nom: str, visible: bool):
        """Allume ou éteint un calque du décalquage (voir CALQUES)."""
        if nom not in self.layers:
            return
        self.layers[nom] = bool(visible)
        if nom == "grille":
            self.grid_visible = bool(visible)
        self.apply_layers()

    def apply_layers(self):
        """Applique l'état des calques aux objets présents dans la scène."""
        if self.pixmap_item is not None:
            self.pixmap_item.setVisible(self.layers["fond"])
        if self.grid_group is not None:
            self.grid_group.setVisible(self.layers["grille"])
        for it in self.object_items:
            it.setVisible(self.layers["cales"])
        for it in self.zone_items:
            it.setVisible(self.layers["zones"])
        for it in self.obstacle_items:
            it.setVisible(self.layers["obstacles"])
        for it in self.epontille_items:
            it.setVisible(self.layers.get("epontilles", True))
        for it in self.annotation_items:
            it.setVisible(self.layers.get("info", True))
        if self.construction_group is not None:
            self.construction_group.setVisible(self.layers.get("construction", True))

    def n_zones(self):
        """(zones de charge, zones interdites/hauteur) dessinées sur ce plan."""
        return len(self.zone_items), len(self.obstacle_items)

    # ------------------------------------------ traits de construction
    def _build_construction(self):
        """Les traits qu'on tire soi-même pour décalquer (voir
        `lignes_de_construction`)."""
        group, self.construction_lines = groupe_de_construction(
            self.calibrated, self.pixmap_item.boundingRect())
        return group

    def snap_construction(self, x, y, radius):
        """Accroche aux traits de construction : (point, force) ou None."""
        return accrocher_construction(
            getattr(self, "construction_lines", None), x, y, radius)

    def _build_grid(self) -> QGraphicsItemGroup:
        cal = self.calibrated.calibration
        rect = self.pixmap_item.boundingRect()
        corners = [cal.to_real(rect.left(), rect.top()),
                   cal.to_real(rect.right(), rect.top()),
                   cal.to_real(rect.right(), rect.bottom()),
                   cal.to_real(rect.left(), rect.bottom())]
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        step1 = nice_step(x1 - x0, 12)
        step2 = nice_step(y1 - y0, 15)
        group = QGraphicsItemGroup()
        ax1, ax2 = self.calibrated.axes
        font = QFont()
        font.setPointSizeF(8.5)
        pen1 = QPen(QColor(theme.GRID_X), 0)
        pen1.setCosmetic(True)
        pen1.setStyle(Qt.PenStyle.DashLine)
        pen2 = QPen(QColor(theme.GRID_Y), 0)
        pen2.setCosmetic(True)
        pen2.setStyle(Qt.PenStyle.DashLine)

        def add_line(p1, p2, pen):
            u1, v1 = cal.to_pixel(*p1)
            u2, v2 = cal.to_pixel(*p2)
            li = QGraphicsLineItem(QLineF(u1, v1, u2, v2))
            li.setPen(pen)
            group.addToGroup(li)
            return (u1, v1)

        def add_label(text, u, v, color):
            t = QGraphicsSimpleTextItem(text)
            t.setFont(font)
            t.setBrush(QBrush(color))
            t.setPos(u + 2, v + 2)
            t.setFlag(t.GraphicsItemFlag.ItemIgnoresTransformations, True)
            group.addToGroup(t)

        a = math.ceil(x0 / step1) * step1
        while a <= x1 + 1e-9:
            u1, v1 = add_line((a, y0), (a, y1), pen1)
            add_label(f"{ax1}={a:g}", u1,
                      self.pixmap_item.boundingRect().top() + 4, theme.GRID_X.darker(150))
            a += step1
        b = math.ceil(y0 / step2) * step2
        while b <= y1 + 1e-9:
            u1, v1 = add_line((x0, b), (x1, b), pen2)
            add_label(f"{ax2}={b:g}", self.pixmap_item.boundingRect().left() + 4,
                      v1, theme.GRID_Y.darker(150))
            b += step2
        return group
