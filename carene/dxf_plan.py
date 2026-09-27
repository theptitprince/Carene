# -*- coding: utf-8 -*-
"""Fond de plan DXF : lecture des traits, calques, rendu en image, accroche.

Le DXF est le **format pivot** qu'on demande au chantier (décision D-9) : il
porte les traits aux coordonnées exactes, ses calques, et le plus souvent
l'échelle 1:1 en millimètres. Le DWG, lui, se convertit à la main avec ODA
File Converter avant import — le logiciel n'en lit aucun et n'en lance aucun.

Ce que fait ce module, sans une ligne de Qt (il se teste seul) :

1. **lire** un DXF (R12 → R2018) et aplatir ce qui est un trait — LINE,
   LWPOLYLINE, POLYLINE, ARC, CIRCLE, ELLIPSE, SPLINE et surtout **INSERT**
   (les références de blocs, récursivement et avec leur transformation : un
   plan de chantier n'est presque que des blocs) ;
2. **compter** ce qu'il n'a pas su lire, par type d'entité, et le dire. Un
   trait perdu en silence, c'est une cloison manquante, donc une cale
   décalquée trop grande et une pose acceptée à tort (D-9) ;
3. **rendre** les calques retenus en PNG à la résolution choisie, rangé à côté
   des autres plans du navire. Tout l'aval du logiciel (calage, décalquage,
   chargement) ne voit que cette image : le chemin DXF rejoint donc le chemin
   PDF sans rien changer ailleurs ;
4. rendre les **sommets** du dessin dans le repère pixel de cette image, pour
   que le curseur s'y accroche au calage et au tracé (D-24), avec la même
   classe `SnapIndex` que `pdf_plan` — l'éditeur se sert de l'un ou de l'autre
   sans savoir lequel ;
5. lire l'**unité** du dessin ($INSUNITS) pour proposer un calage
   pré-rempli sur les coordonnées mêmes du dessin, au lieu de cliquer deux
   points. Proposé, jamais imposé : le calage manuel — et l'ajustement de
   l'échelle sur les traits de couples (D-11) — reste disponible et prime.

Repère pixel du rendu :

    u = (x_dxf − x_gauche) × résolution
    v = (y_haut − y_dxf) × résolution        (Y du dessin monte, celui de
                                              l'image descend)

`origine = (x_gauche, y_haut)` et `résolution` (pixels par unité DXF) sont
mémorisés dans le plan calé : un re-rendu retombe **exactement** sur les mêmes
pixels, donc le calage et les tracés survivent à la perte de l'image.

Ce que ce module produit sert à la vue et aux contrôles de pose, jamais au
calcul de stabilité (D-10).
"""
from __future__ import annotations

import hashlib
import math
import os
import struct
import threading
import zlib

import numpy as np

from .pdf_plan import SnapIndex, intersections, snap  # noqa: F401 — même accroche

# Résolution par défaut : le rendu vise cette largeur en pixels, ce qui
# donne un fond lisible sans écraser la mémoire quelle que soit l'unité du
# dessin (un plan en mm et le même en m doivent sortir pareil).
LARGEUR_CIBLE_DEFAUT = 6000
PIXELS_MAX_PAR_COTE = 14000
MARGE_PX = 12          # petite marge blanche autour du dessin

# Finesse d'aplatissement des courbes : une corde s'écarte de l'arc d'au plus
# (taille de l'entité / DIVISEUR_FLECHE). Relatif, donc indépendant de l'unité.
DIVISEUR_FLECHE = 400.0

# Entités qu'on sait transformer en traits. Le reste est compté, pas ignoré.
TYPES_LUS = ("LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE",
             "SPLINE", "INSERT")

PROFONDEUR_BLOCS_MAX = 12      # garde-fou contre un bloc qui s'appelle lui-même

# $INSUNITS : code → (nom lisible, mètres par unité). None = on ne sait pas
# convertir, donc on ne propose pas de calage automatique.
UNITES = {
    0: ("unité non déclarée", None),
    1: ("pouces", 0.0254),
    2: ("pieds", 0.3048),
    3: ("milles", 1609.344),
    4: ("millimètres", 0.001),
    5: ("centimètres", 0.01),
    6: ("mètres", 1.0),
    7: ("kilomètres", 1000.0),
    8: ("micropouces", 2.54e-8),
    9: ("mils", 2.54e-5),
    10: ("yards", 0.9144),
    11: ("ångströms", 1e-10),
    12: ("nanomètres", 1e-9),
    13: ("microns", 1e-6),
    14: ("décimètres", 0.1),
    15: ("décamètres", 10.0),
    16: ("hectomètres", 100.0),
    17: ("gigamètres", 1e9),
    18: ("unités astronomiques", 1.495978707e11),
    19: ("années-lumière", 9.4607304725808e15),
    20: ("parsecs", 3.0856775814913673e16),
    21: ("pieds US", 1200.0 / 3937.0),
}


def _ezdxf():
    try:
        import ezdxf
    except ImportError as e:      # pragma: no cover — dépendance déclarée
        raise ImportError(
            "Le module ezdxf manque : installez-le (pip install ezdxf) pour "
            "importer des plans DXF.") from e
    return ezdxf


# ------------------------------------------------------------------ le dessin
class Dessin:
    """Un DXF lu une fois : ses traits aplatis, ses sommets, ses calques.

    Les polylignes sont rangées à plat — un seul tableau de points et les
    indices de début — plutôt qu'en liste de petits tableaux : un plan
    d'ensemble en compte des centaines de milliers, et Python ne tient pas la
    charge avec un objet par trait.
    """

    def __init__(self):
        self.chemin = ""
        self.version = ""
        self.calques: list[str] = []          # noms, ordre de première apparition
        self._rang = {}                       # nom de calque → indice
        self.points = np.zeros((0, 2))        # (P,2) tous les points aplatis
        self.debuts = np.zeros(1, dtype=np.int64)   # (L+1,) bornes des polylignes
        self.poly_calque = np.zeros(0, dtype=np.int32)
        self.sommets = np.zeros((0, 2))       # (N,2) sommets d'accroche
        self.sommets_calque = np.zeros(0, dtype=np.int32)
        self.compte_traits = {}               # calque → nb de polylignes
        self.compte_sommets = {}              # calque → nb de sommets
        self.non_lus = {}                     # type d'entité → nombre
        self.blocs_manquants = {}             # nom de bloc → nombre de renvois
        self.blocs_trop_profonds = 0
        self.unite_code = 0
        self.entites = 0                      # entités parcourues (blocs déployés)

    # --------------------------------------------------------------- unités
    @property
    def unite_nom(self) -> str:
        return UNITES.get(int(self.unite_code), ("unité inconnue", None))[0]

    @property
    def metres_par_unite(self):
        """Mètres pour une unité de dessin, ou None si le DXF ne le dit pas."""
        return UNITES.get(int(self.unite_code), (None, None))[1]

    @property
    def unite_connue(self) -> bool:
        return self.metres_par_unite is not None

    # --------------------------------------------------------------- calques
    def n_polylignes(self) -> int:
        return len(self.poly_calque)

    def _masque_poly(self, calques=None):
        if calques is None:
            return np.ones(len(self.poly_calque), dtype=bool)
        rangs = [self._rang[c] for c in calques if c in self._rang]
        if not rangs:
            return np.zeros(len(self.poly_calque), dtype=bool)
        return np.isin(self.poly_calque, np.asarray(rangs, dtype=np.int32))

    def polylignes(self, calques=None):
        """Itère les polylignes retenues, chacune un tableau (n,2) en unités
        DXF. `calques=None` : tout le dessin."""
        garde = self._masque_poly(calques)
        for i in np.nonzero(garde)[0]:
            yield self.points[self.debuts[i]:self.debuts[i + 1]]

    def segments(self, calques=None) -> np.ndarray:
        """(M,4) : x1, y1, x2, y2 de chaque segment droit, en unités DXF.
        C'est ce que le rendu dessine et ce dont on tire les croisements."""
        morceaux = []
        for poly in self.polylignes(calques):
            if len(poly) >= 2:
                morceaux.append(np.hstack([poly[:-1], poly[1:]]))
        if not morceaux:
            return np.zeros((0, 4))
        return np.vstack(morceaux)

    def sommets_de(self, calques=None) -> np.ndarray:
        """(N,2) sommets d'accroche des calques retenus, en unités DXF."""
        if calques is None:
            return self.sommets
        rangs = [self._rang[c] for c in calques if c in self._rang]
        if not rangs or len(self.sommets) == 0:
            return np.zeros((0, 2))
        garde = np.isin(self.sommets_calque, np.asarray(rangs, dtype=np.int32))
        return self.sommets[garde]

    def infos_calques(self, calques=None):
        """[(nom, nb de traits, nb de sommets)] pour lister les calques et
        éteindre le bruit (cartouche, hachures, cotation)."""
        return [(c, int(self.compte_traits.get(c, 0)),
                 int(self.compte_sommets.get(c, 0))) for c in self.calques]

    # --------------------------------------------------------------- étendue
    def etendue(self, calques=None):
        """(x_min, y_min, x_max, y_max) en unités DXF, ou None si rien à
        montrer sur les calques retenus."""
        garde = self._masque_poly(calques)
        if not garde.any() or len(self.points) == 0:
            return None
        if garde.all():
            P = self.points
        else:
            morceaux = [self.points[self.debuts[i]:self.debuts[i + 1]]
                        for i in np.nonzero(garde)[0]]
            P = np.vstack(morceaux) if morceaux else np.zeros((0, 2))
        if len(P) == 0:
            return None
        return (float(P[:, 0].min()), float(P[:, 1].min()),
                float(P[:, 0].max()), float(P[:, 1].max()))

    # --------------------------------------------------------------- constat
    def avertissements(self) -> list[str]:
        """Ce que la lecture n'a pas su faire, en toutes lettres — rien n'est
        passé sous silence (D-9)."""
        out = []
        if self.non_lus:
            détail = ", ".join(f"{n} {t}" for t, n in
                               sorted(self.non_lus.items(), key=lambda kv: -kv[1]))
            out.append(f"{sum(self.non_lus.values())} entité(s) non lue(s) — "
                       f"{détail}. Ces traits ne sont ni dessinés ni "
                       "accrochables : vérifiez qu'ils ne portent pas une "
                       "cloison.")
        if self.blocs_manquants:
            noms = ", ".join(sorted(self.blocs_manquants))
            out.append(f"{sum(self.blocs_manquants.values())} renvoi(s) vers "
                       f"un bloc absent du fichier ({noms}) : le DXF est "
                       "incomplet, redemandez-le au chantier.")
        if self.blocs_trop_profonds:
            out.append(f"{self.blocs_trop_profonds} bloc(s) imbriqué(s) au-delà "
                       f"de {PROFONDEUR_BLOCS_MAX} niveaux : contenu ignoré.")
        if not self.unite_connue:
            out.append("Le dessin ne déclare pas son unité ($INSUNITS) : le "
                       "calage sur ses coordonnées n'est pas proposé, calez-le "
                       "sur deux points connus.")
        if not self.n_polylignes():
            out.append("Aucun trait lisible dans ce fichier.")
        return out

    def resume(self) -> str:
        u = self.unite_nom
        return (f"{self.n_polylignes()} traits, {len(self.sommets)} sommets, "
                f"{len(self.calques)} calques, unité : {u}")


# ------------------------------------------------------------------ lecture
def _fleche(pts) -> float:
    """Tolérance d'aplatissement d'une courbe : une fraction de sa taille, pour
    qu'un arc de 3 mm et un arc de 30 m soient tous deux lisses."""
    if pts is None or len(pts) == 0:
        return 1e-6
    A = np.asarray([(p[0], p[1]) for p in pts], dtype=float)
    diag = math.hypot(float(A[:, 0].max() - A[:, 0].min()),
                      float(A[:, 1].max() - A[:, 1].min()))
    return max(diag / DIVISEUR_FLECHE, 1e-9)


def _aplatir_chemin(e):
    """Points (n,2) d'une entité courbe, via le chemin ezdxf."""
    from ezdxf import path as ezpath
    p = ezpath.make_path(e)
    ctrl = list(p.control_vertices())
    pts = [(v.x, v.y) for v in p.flattening(_fleche(ctrl))]
    return np.asarray(pts, dtype=float).reshape(-1, 2)


def _quadrants(cx, cy, r):
    return [(cx + r, cy), (cx, cy + r), (cx - r, cy), (cx, cy - r)]


class _Lecteur:
    """Parcours d'un DXF : accumule traits et sommets, compte le reste."""

    def __init__(self, dessin: Dessin):
        self.d = dessin
        self._pts = []            # morceaux de polylignes (tableaux (n,2))
        self._deb = [0]
        self._pcal = []
        self._som = []
        self._scal = []
        self._n = 0

    # -- accumulation
    def _rang(self, calque: str) -> int:
        r = self.d._rang.get(calque)
        if r is None:
            r = len(self.d.calques)
            self.d._rang[calque] = r
            self.d.calques.append(calque)
        return r

    def trait(self, pts, calque):
        P = np.asarray(pts, dtype=float).reshape(-1, 2)
        if len(P) < 2:
            return
        fini = np.isfinite(P).all(axis=1)
        if not fini.all():
            P = P[fini]
            if len(P) < 2:
                return
        self._pts.append(P)
        self._n += len(P)
        self._deb.append(self._n)
        self._pcal.append(self._rang(calque))

    def sommet(self, pts, calque):
        r = self._rang(calque)
        for p in pts:
            x, y = float(p[0]), float(p[1])
            if math.isfinite(x) and math.isfinite(y):
                self._som.append((x, y))
                self._scal.append(r)

    def non_lu(self, typ):
        self.d.non_lus[typ] = self.d.non_lus.get(typ, 0) + 1

    # -- parcours
    def entites(self, iterable, calque_hote=None, profondeur=0):
        for e in iterable:
            self.une(e, calque_hote, profondeur)

    def une(self, e, calque_hote=None, profondeur=0):
        typ = e.dxftype()
        self.d.entites += 1
        calque = e.dxf.get("layer", "0") or "0"
        # règle AutoCAD : dans un bloc, le calque « 0 » prend celui du renvoi
        if calque_hote is not None and calque == "0":
            calque = calque_hote
        try:
            self._une(e, typ, calque, profondeur)
        except Exception:
            # une entité tordue ne doit pas faire tomber la lecture du plan :
            # elle est comptée comme non lue, et l'utilisateur le voit
            self.non_lu(typ)

    def _une(self, e, typ, calque, profondeur):
        if typ == "LINE":
            a, b = e.dxf.start, e.dxf.end
            self.trait([(a.x, a.y), (b.x, b.y)], calque)
            self.sommet([(a.x, a.y), (b.x, b.y)], calque)
        elif typ == "LWPOLYLINE":
            self._lwpolyline(e, calque)
        elif typ == "POLYLINE":
            self._polyline(e, calque)
        elif typ == "ARC":
            self.trait(_aplatir_chemin(e), calque)
            c, s, f = e.dxf.center, e.start_point, e.end_point
            self.sommet([(s.x, s.y), (f.x, f.y), (c.x, c.y)], calque)
        elif typ == "CIRCLE":
            self.trait(_aplatir_chemin(e), calque)
            c, r = e.dxf.center, float(e.dxf.radius)
            self.sommet([(c.x, c.y)] + _quadrants(c.x, c.y, r), calque)
        elif typ == "ELLIPSE":
            self.trait(_aplatir_chemin(e), calque)
            c, s, f = e.dxf.center, e.start_point, e.end_point
            self.sommet([(s.x, s.y), (f.x, f.y), (c.x, c.y)], calque)
        elif typ == "SPLINE":
            P = _aplatir_chemin(e)
            self.trait(P, calque)
            # comme pour une Bézier de PDF : seules les extrémités sont des
            # sommets sûrs, les points intermédiaires ne sont qu'un maillage
            if len(P) >= 2:
                self.sommet([P[0], P[-1]], calque)
        elif typ == "INSERT":
            self._insert(e, calque, profondeur)
        else:
            self.non_lu(typ)

    def _lwpolyline(self, e, calque):
        brut = list(e.get_points("xyb"))
        sommets = [(float(p[0]), float(p[1])) for p in brut]
        if not sommets:
            return
        courbe = any(abs(float(p[2])) > 1e-12 for p in brut)
        if courbe:
            self.trait(_aplatir_chemin(e), calque)
        else:
            pts = list(sommets)
            if e.closed and len(pts) > 2:
                pts.append(pts[0])
            self.trait(pts, calque)
        # les sommets déclarés, pas le maillage des arcs de raccordement
        self.sommet(sommets, calque)

    def _polyline(self, e, calque):
        mode = e.get_mode()
        if mode not in ("AcDb2dPolyline", "AcDb3dPolyline"):
            # maillage ou face : ce n'est pas un trait de plan
            self.non_lu(f"POLYLINE ({mode})")
            return
        sommets = [(float(v.dxf.location.x), float(v.dxf.location.y))
                   for v in e.vertices]
        if len(sommets) < 2:
            return
        courbe = any(abs(float(v.dxf.get("bulge", 0.0) or 0.0)) > 1e-12
                     for v in e.vertices)
        if courbe:
            self.trait(_aplatir_chemin(e), calque)
        else:
            pts = list(sommets)
            if e.is_closed and len(pts) > 2:
                pts.append(pts[0])
            self.trait(pts, calque)
        self.sommet(sommets, calque)

    def _insert(self, e, calque, profondeur):
        """Un renvoi de bloc, déployé **avec sa transformation** (position,
        échelles, rotation, réseau MINSERT) et récursivement : un plan de
        chantier n'est presque que ça."""
        if profondeur >= PROFONDEUR_BLOCS_MAX:
            self.d.blocs_trop_profonds += 1
            return
        nom = e.dxf.get("name", "?")
        try:
            filles = list(e.virtual_entities())
        except Exception:
            self.d.blocs_manquants[nom] = self.d.blocs_manquants.get(nom, 0) + 1
            return
        # le point d'insertion est un point du dessin : on s'y accroche
        try:
            p = e.dxf.insert
            self.sommet([(p.x, p.y)], calque)
        except Exception:
            pass
        self.entites(filles, calque_hote=calque, profondeur=profondeur + 1)

    # -- résultat
    def terminer(self):
        d = self.d
        d.points = (np.vstack(self._pts) if self._pts else np.zeros((0, 2)))
        d.debuts = np.asarray(self._deb, dtype=np.int64)
        d.poly_calque = np.asarray(self._pcal, dtype=np.int32)
        d.sommets = np.asarray(self._som, dtype=float).reshape(-1, 2)
        d.sommets_calque = np.asarray(self._scal, dtype=np.int32)
        for c in d.calques:
            r = d._rang[c]
            d.compte_traits[c] = int(np.count_nonzero(d.poly_calque == r))
            d.compte_sommets[c] = int(np.count_nonzero(d.sommets_calque == r))
        return d


def lire(chemin: str) -> Dessin:
    """Lit un DXF (R12 → R2018) et rend un `Dessin`. Lève une exception si le
    fichier n'est pas un DXF lisible du tout ; une entité isolée illisible,
    elle, est comptée (voir `Dessin.avertissements`)."""
    ezdxf = _ezdxf()
    try:
        doc = ezdxf.readfile(chemin)
    except ezdxf.DXFStructureError as e:
        # un DXF abîmé (transfert tronqué, éditeur exotique) : on tente le
        # rattrapage d'ezdxf plutôt que d'abandonner
        from ezdxf import recover
        doc, verif = recover.readfile(chemin)
        if verif.errors:
            pass          # les erreurs restantes se verront dans les comptes
    d = Dessin()
    d.chemin = os.path.abspath(chemin)
    d.version = str(doc.dxfversion)
    try:
        d.unite_code = int(doc.header.get("$INSUNITS", 0) or 0)
    except Exception:
        d.unite_code = 0
    # les calques déclarés existent même vides : on les liste dans l'ordre du
    # fichier, ceux qui portent des traits se rempliront ensuite
    lec = _Lecteur(d)
    try:
        for couche in doc.layers:
            lec._rang(couche.dxf.name)
    except Exception:
        pass
    lec.entites(doc.modelspace())
    return lec.terminer()


# ------------------------------------------------------------------ cache
_DESSINS = {}
_DESSINS_MAX = 4
# la lecture des sommets tourne dans un fil de fond (voir `scene.ChargeurTraits`)
# pendant que l'interface interroge les mêmes caches : un verrou, et personne
# ne voit un cache à moitié vidé
_VERROU = threading.Lock()


def _cle_fichier(chemin):
    try:
        mtime = os.path.getmtime(chemin)
    except OSError:
        mtime = 0
    return (os.path.abspath(chemin), mtime)


def dessin_pour(chemin: str) -> Dessin:
    """Le `Dessin` d'un fichier, lu une seule fois par session (la lecture
    d'un plan de chantier prend quelques secondes)."""
    cle = _cle_fichier(chemin)
    with _VERROU:
        d = _DESSINS.get(cle)
    if d is None:
        d = lire(chemin)
        with _VERROU:
            while len(_DESSINS) >= _DESSINS_MAX:
                _DESSINS.pop(next(iter(_DESSINS)))
            _DESSINS[cle] = d
    return d


def dessin_en_cache(chemin: str):
    """Le `Dessin` s'il est déjà lu, sans rien ouvrir."""
    if not chemin:
        return None
    with _VERROU:
        return _DESSINS.get(_cle_fichier(chemin))


def oublier(chemin: str = ""):
    """Vide le cache (tests, ou fichier remplacé à chaud)."""
    with _VERROU:
        if not chemin:
            _DESSINS.clear()
        else:
            _DESSINS.pop(_cle_fichier(chemin), None)


# ------------------------------------------------------------------ cadrage
def cadrage(dessin: Dessin, calques=None, resolution: float = 0.0,
            largeur_cible: int = LARGEUR_CIBLE_DEFAUT, marge_px: int = MARGE_PX):
    """(largeur_px, hauteur_px, origine, résolution) du rendu.

    `résolution` en pixels par unité DXF ; à 0 elle est déduite de
    `largeur_cible`, ce qui donne la même image que le dessin soit en
    millimètres ou en mètres. `origine` = coordonnées DXF du coin haut-gauche
    de l'image, marge comprise."""
    ext = dessin.etendue(calques)
    if ext is None:
        raise ValueError(
            "Aucun trait sur les calques retenus : rien à rendre. "
            "Rallumez au moins un calque.")
    x0, y0, x1, y1 = ext
    largeur_u = max(x1 - x0, 1e-9)
    hauteur_u = max(y1 - y0, 1e-9)
    res = float(resolution)
    if res <= 0:
        res = max(int(largeur_cible) - 2 * marge_px, 1) / largeur_u
    w = int(math.ceil(largeur_u * res)) + 2 * marge_px
    h = int(math.ceil(hauteur_u * res)) + 2 * marge_px
    origine = (x0 - marge_px / res, y1 + marge_px / res)
    return w, h, origine, res


def vers_pixels(pts, origine, resolution) -> np.ndarray:
    """Unités DXF → pixels de l'image rendue (Y retourné)."""
    P = np.asarray(pts, dtype=float).reshape(-1, 2)
    if len(P) == 0:
        return P
    out = np.empty_like(P)
    out[:, 0] = (P[:, 0] - origine[0]) * resolution
    out[:, 1] = (origine[1] - P[:, 1]) * resolution
    return out


def vers_dxf(u, v, origine, resolution):
    """Pixels de l'image → unités DXF."""
    return (origine[0] + u / resolution, origine[1] - v / resolution)


# ------------------------------------------------------------------ rendu
_LIMITE_ECHANTILLONS = 1_500_000      # bornes mémoire du tracé (≈ 120 Mo)


def _rasteriser(segs_px: np.ndarray, w: int, h: int) -> np.ndarray:
    """Encre (h,w) float32 dans [0,1] pour des segments déjà en pixels.

    Trait d'un pixel, adouci façon Wu : on marche le long du grand axe et on
    partage l'intensité entre les deux pixels voisins du petit axe. Tout est
    vectorisé — un plan de chantier compte des centaines de milliers de
    segments, une boucle Python y prendrait des minutes."""
    encre = np.zeros(w * h, dtype=np.float32)
    if len(segs_px) == 0:
        return encre.reshape(h, w)
    S = np.asarray(segs_px, dtype=np.float64).reshape(-1, 4)
    S = S[np.isfinite(S).all(axis=1)]
    # rejet des segments franchement hors image (cadres, repères lointains)
    dedans = ~((np.maximum(S[:, 0], S[:, 2]) < -1) | (np.minimum(S[:, 0], S[:, 2]) > w)
               | (np.maximum(S[:, 1], S[:, 3]) < -1) | (np.minimum(S[:, 1], S[:, 3]) > h))
    S = S[dedans]
    if len(S) == 0:
        return encre.reshape(h, w)
    raide = np.abs(S[:, 3] - S[:, 1]) > np.abs(S[:, 2] - S[:, 0])
    X1 = np.where(raide, S[:, 1], S[:, 0])
    Y1 = np.where(raide, S[:, 0], S[:, 1])
    X2 = np.where(raide, S[:, 3], S[:, 2])
    Y2 = np.where(raide, S[:, 2], S[:, 3])
    n = np.ceil(np.abs(X2 - X1)).astype(np.int64) + 1
    n = np.minimum(n, 4 * max(w, h) + 4)
    # découpage en paquets d'échantillons pour tenir la mémoire
    cum = np.cumsum(n)
    debut = 0
    while debut < len(S):
        base = cum[debut - 1] if debut else 0
        fin = int(np.searchsorted(cum, base + _LIMITE_ECHANTILLONS, side="right"))
        fin = max(fin, debut + 1)
        sl = slice(debut, fin)
        _encrer(encre, X1[sl], Y1[sl], X2[sl], Y2[sl], n[sl], raide[sl], w, h)
        debut = fin
    return np.clip(encre, 0.0, 1.0).reshape(h, w)


def _encrer(encre, X1, Y1, X2, Y2, n, raide, w, h):
    m = len(n)
    idx = np.repeat(np.arange(m), n)
    depart = np.repeat(np.cumsum(n) - n, n)
    k = np.arange(len(idx), dtype=np.float64) - depart
    denom = np.repeat(np.maximum(n - 1, 1), n).astype(np.float64)
    t = k / denom
    px = X1[idx] + t * (X2[idx] - X1[idx])
    py = Y1[idx] + t * (Y2[idx] - Y1[idx])
    ix = np.rint(px).astype(np.int64)
    jy = np.floor(py).astype(np.int64)
    fy = (py - jy).astype(np.float32)
    r = raide[idx]
    for dj, poids in ((0, 1.0 - fy), (1, fy)):
        rr = np.where(r, ix, jy + dj)
        cc = np.where(r, jy + dj, ix)
        ok = (rr >= 0) & (rr < h) & (cc >= 0) & (cc < w) & (poids > 1e-3)
        if not ok.any():
            continue
        plat = rr[ok] * w + cc[ok]
        np.add.at(encre, plat, poids[ok])


def _png_octets(image: np.ndarray) -> bytes:
    """PNG 8 bits en niveaux de gris, écrit à la main : pas de dépendance
    d'image en plus (et rien de neuf à embarquer dans l'exécutable)."""
    h, w = image.shape
    lignes = np.hstack([np.zeros((h, 1), np.uint8), image]).tobytes()

    def bloc(typ, data):
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + bloc(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + bloc(b"IDAT", zlib.compress(lignes, 3))
            + bloc(b"IEND", b""))


def _ecrire_png(chemin: str, image: np.ndarray):
    dossier = os.path.dirname(os.path.abspath(chemin))
    if dossier:
        os.makedirs(dossier, exist_ok=True)
    with open(chemin, "wb") as f:
        f.write(_png_octets(image))


def rendre_cadre(dessin: Dessin, out_png: str, calques, origine, resolution,
                 largeur: int, hauteur: int):
    """Rend les calques retenus dans un cadre **imposé** : même origine, même
    résolution, même taille qu'un rendu précédent.

    C'est ce qui permet de refaire l'image d'un plan perdue (dossier recopié
    sans ses rendus) en retombant **exactement** sur les mêmes pixels : le
    calage et les tracés faits dessus restent bons."""
    w, h = int(largeur), int(hauteur)
    segs = dessin.segments(calques)
    if len(segs):
        px = np.hstack([vers_pixels(segs[:, :2], origine, resolution),
                        vers_pixels(segs[:, 2:], origine, resolution)])
    else:
        px = np.zeros((0, 4))
    encre = _rasteriser(px, w, h)
    _ecrire_png(out_png, (255.0 - 255.0 * encre).astype(np.uint8))
    return w, h, (float(origine[0]), float(origine[1])), float(resolution)


def rendre(dessin: Dessin, out_png: str, calques=None, resolution: float = 0.0,
           largeur_cible: int = LARGEUR_CIBLE_DEFAUT, marge_px: int = MARGE_PX):
    """Rend les calques retenus en PNG (traits noirs sur blanc).

    Renvoie (largeur, hauteur, origine, résolution) : c'est la transformation
    pixel ↔ unité DXF, à mémoriser avec le plan pour pouvoir tout refaire à
    l'identique (voir `rendre_cadre`). Refuse une image démesurée plutôt que
    d'étouffer l'application, et le message dit quelle résolution passerait."""
    w, h, origine, res = cadrage(dessin, calques, resolution, largeur_cible,
                                 marge_px)
    if max(w, h) > PIXELS_MAX_PAR_COTE:
        res_ok = res * PIXELS_MAX_PAR_COTE / max(w, h)
        raise ValueError(
            f"À cette résolution l'image ferait {w} × {h} pixels, trop pour "
            f"être affichée. Descendez à {res_ok:.4g} pixel(s) par unité de "
            "dessin au plus.")
    return rendre_cadre(dessin, out_png, calques, origine, res, w, h)


def apercu_png(dessin: Dessin, calques=None, largeur_px: int = 420) -> bytes:
    """Petit rendu PNG (octets) des calques retenus, pour l'aperçu du choix
    des calques — on voit tout de suite ce que le cartouche encombre."""
    w, h, origine, res = cadrage(dessin, calques, 0.0, int(largeur_px), 4)
    segs = dessin.segments(calques)
    if len(segs):
        px = np.hstack([vers_pixels(segs[:, :2], origine, res),
                        vers_pixels(segs[:, 2:], origine, res)])
    else:
        px = np.zeros((0, 4))
    encre = _rasteriser(px, w, h)
    return _png_octets((255.0 - 255.0 * encre).astype(np.uint8))


def import_into(dxf_path: str, ship_folder: str, calques=None,
                resolution: float = 0.0,
                largeur_cible: int = LARGEUR_CIBLE_DEFAUT):
    """Range un plan DXF dans le dossier du navire : copie du DXF dans
    `plans/` (un navire est un dossier qu'on emporte tel quel — le re-rendu et
    l'accroche doivent y survivre) et rendu des calques retenus en PNG à côté.

    Renvoie (chemin_png, chemin_dxf, largeur, hauteur, origine, résolution)."""
    import shutil
    plans = os.path.abspath(os.path.join(ship_folder, "plans"))
    os.makedirs(plans, exist_ok=True)
    src = os.path.abspath(dxf_path)
    ship = os.path.abspath(ship_folder)
    try:
        dedans = os.path.commonpath([src, ship]) == ship
    except ValueError:            # autre lecteur (Windows)
        dedans = False
    dest = src
    if not dedans:
        dest = os.path.join(plans, os.path.basename(src))
        try:
            if not (os.path.exists(dest)
                    and os.path.getsize(dest) == os.path.getsize(src)):
                shutil.copy2(src, dest)
        except OSError:
            dest = src
    dessin = dessin_pour(dest if os.path.exists(dest) else src)
    base = os.path.splitext(os.path.basename(src))[0]
    # Le nom du rendu porte de quoi le distinguer d'un autre JEU de calques —
    # une empreinte, pas seulement le nombre : deux vues du même DXF prenant
    # des calques différents mais aussi nombreux (le profil et un pont, par
    # exemple) écrivaient le même PNG, et la seconde imposait son cadrage à la
    # première — plan calé sur une image qui n'est plus la sienne.
    if calques is None:
        marque = "tous"
    else:
        noms = sorted(calques)
        empreinte = hashlib.sha1("|".join(noms).encode("utf-8")).hexdigest()[:8]
        marque = f"{len(noms)}c{empreinte}"
    out = os.path.join(plans, f"{base}_dxf_{marque}_{int(largeur_cible)}px.png")
    w, h, origine, res = rendre(dessin, out, calques, resolution, largeur_cible)
    return out, dest, w, h, origine, res


# ------------------------------------------------------------------ sommets
def extract_vertices(dxf_path: str, calques=None, origine=(0.0, 0.0),
                     resolution: float = 1.0,
                     with_intersections: bool = True) -> np.ndarray:
    """Sommets (N,2) en pixels de l'image rendue avec la même origine et la
    même résolution — même contrat que `pdf_plan.extract_vertices`.

    On y ajoute les croisements francs de traits : sur un plan de chantier,
    l'angle d'une cloison est souvent un croisement, pas une extrémité."""
    dessin = dessin_pour(dxf_path)
    P = vers_pixels(dessin.sommets_de(calques), origine, resolution)
    if with_intersections:
        segs = dessin.segments(calques)
        if len(segs):
            spx = np.hstack([vers_pixels(segs[:, :2], origine, resolution),
                             vers_pixels(segs[:, 2:], origine, resolution)])
            X = intersections(spx)
            if len(X):
                P = np.vstack([P, X]) if len(P) else X
    if len(P) == 0:
        return np.zeros((0, 2))
    q = np.round(P / 0.1).astype(np.int64)
    _, idx = np.unique(q, axis=0, return_index=True)
    return np.ascontiguousarray(P[np.sort(idx)], dtype=np.float64)


# ------------------------------------------------------------------ accroche
_INDEX = {}
_INDEX_MAX = 6


def cle_cache(dxf_path, calques=None, origine=(0.0, 0.0), resolution=1.0):
    """Clé de session d'un index d'accroche — même forme que celle de
    `pdf_plan`, pour que l'éditeur traite les deux sources pareil."""
    cal = None if calques is None else tuple(sorted(calques))
    return (_cle_fichier(dxf_path), cal, (float(origine[0]), float(origine[1])),
            float(resolution))


def ranger_index(cle, index):
    """Range un index **fini** (jamais un index à moitié construit : c'est ce
    qui permet de le calculer dans un fil de fond)."""
    if index is None:
        return
    with _VERROU:
        while len(_INDEX) >= _INDEX_MAX:
            _INDEX.pop(next(iter(_INDEX)))
        _INDEX[cle] = index


def snap_index_cached(dxf_path, calques=None, origine=(0.0, 0.0),
                      resolution=1.0):
    """L'index s'il est déjà en mémoire, sans rien lire."""
    if not dxf_path:
        return None
    with _VERROU:
        return _INDEX.get(cle_cache(dxf_path, calques, origine, resolution))


def snap_index_for(dxf_path, calques=None, origine=(0.0, 0.0), resolution=1.0):
    """Index d'accroche des traits du DXF, mémorisé pour la session. None si
    le fichier a disparu."""
    if not dxf_path or not os.path.exists(dxf_path):
        return None
    cle = cle_cache(dxf_path, calques, origine, resolution)
    with _VERROU:
        idx = _INDEX.get(cle)
    if idx is None:
        idx = SnapIndex(extract_vertices(dxf_path, calques, origine, resolution))
        ranger_index(cle, idx)
    return idx


def oublier_index():
    with _VERROU:
        _INDEX.clear()


# ------------------------------------------------------------------ calage
def matrice_calage(origine, resolution, metres_par_unite, decalage=(0.0, 0.0)):
    """Matrice 2×3 pixel → repère navire quand le DXF porte ses coordonnées
    réelles (D-9 : c'est le cas courant, mm à 1:1).

    `decalage` : coordonnées navire du point (0, 0) du dessin — un plan de
    chantier a rarement son origine sur la PPAR. Renvoie None si l'unité du
    dessin n'est pas connue : on ne devine pas une échelle en silence."""
    if not metres_par_unite:
        return None
    k = float(metres_par_unite) / float(resolution)
    dx, dy = float(decalage[0]), float(decalage[1])
    return [[k, 0.0, origine[0] * float(metres_par_unite) + dx],
            [0.0, -k, origine[1] * float(metres_par_unite) + dy]]
