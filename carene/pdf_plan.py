# -*- coding: utf-8 -*-
"""Fond de plan PDF : rendu d'une page en image, sommets vectoriels, accroche.

Les plans du navire de référence sortent d'AutoCAD LT en PDF **vectoriel** (décision D-9) :
chaque trait y est un segment aux coordonnées exactes. On ne se contente donc
pas de rastériser la page pour la décalquer à l'œil : on relit les sommets
(extrémités de segments, coins de rectangles, croisements de traits) dans le
**même repère pixel que l'image rendue**, pour que le curseur s'y accroche au
calage et au tracé des contours.

Ce module ne dépend pas de Qt : il se teste seul, et l'éditeur ne fait qu'y
piocher. Ce qu'il produit sert à la vue et aux contrôles de pose, jamais au
calcul de stabilité (D-10).

Repère pixel du rendu — vérifié sur pymupdf 1.28 :

    pixel = (point_page × page.rotation_matrix × Matrix(zoom).prerotate(rot))
            − coin haut-gauche de (page.rect × Matrix(zoom).prerotate(rot)).irect

`page.get_drawings()` renvoie des coordonnées **non tournées** (celles du flux
PDF), alors que `page.rect` et le rendu tiennent compte de la rotation propre
de la page (/Rotate 270 sur les plans du chantier) : d'où `rotation_matrix`.
"""
from __future__ import annotations

import os
import threading

import numpy as np

DPI_DEFAUT = 200
ROTATIONS = (0, 90, 180, 270)
# au-delà, l'image ne tient plus raisonnablement en mémoire (RGBA) ni dans
# une QPixmap : on refuse et on propose de baisser la résolution
PIXELS_MAX_PAR_COTE = 14000


def _pymupdf():
    try:
        import pymupdf
    except ImportError as e:      # pragma: no cover — dépendance déclarée
        raise ImportError(
            "Le module pymupdf manque : installez-le (pip install pymupdf) "
            "pour importer des plans PDF.") from e
    return pymupdf


# ------------------------------------------------------------------ pages
def page_count(path: str) -> int:
    return len(_pymupdf().open(path))


def page_info(path: str):
    """[(largeur_mm, hauteur_mm, rotation_propre)] pour chaque page — de quoi
    lister les pages sans rien rendre."""
    doc = _pymupdf().open(path)
    out = []
    for pg in doc:
        r = pg.rect
        out.append((r.width * 25.4 / 72.0, r.height * 25.4 / 72.0, pg.rotation))
    return out


def _matrice(page, rotation: int, dpi: int):
    """(matrice complète point→pixel, décalage x0, y0 de l'image)."""
    pymupdf = _pymupdf()
    zoom = dpi / 72.0
    m = pymupdf.Matrix(zoom, zoom).prerotate(int(rotation) % 360)
    irect = (page.rect * m).irect
    full = page.rotation_matrix * m
    return full, irect.x0, irect.y0


def taille_rendu(path: str, page: int, rotation: int, dpi: int):
    """(largeur_px, hauteur_px) qu'aurait l'image, sans la rendre."""
    pymupdf = _pymupdf()
    pg = pymupdf.open(path)[page]
    zoom = dpi / 72.0
    m = pymupdf.Matrix(zoom, zoom).prerotate(int(rotation) % 360)
    irect = (pg.rect * m).irect
    return irect.width, irect.height


def render_page(path: str, page: int, rotation: int, dpi: int, out_png: str):
    """Rend la page en PNG (fond blanc, sans alpha). Renvoie (largeur, hauteur).

    Refuse une image démesurée plutôt que de laisser l'application s'étouffer
    en silence : le message dit quelle résolution passerait."""
    pymupdf = _pymupdf()
    pg = pymupdf.open(path)[page]
    w, h = taille_rendu(path, page, rotation, dpi)
    if max(w, h) > PIXELS_MAX_PAR_COTE:
        dpi_ok = int(dpi * PIXELS_MAX_PAR_COTE / max(w, h))
        raise ValueError(
            f"À {dpi} dpi l'image ferait {w} × {h} pixels, trop pour être "
            f"affichée. Choisissez au plus {dpi_ok} dpi.")
    zoom = dpi / 72.0
    m = pymupdf.Matrix(zoom, zoom).prerotate(int(rotation) % 360)
    pix = pg.get_pixmap(matrix=m, alpha=False)
    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    pix.save(out_png)
    return pix.width, pix.height


def apercu_png(path: str, page: int, rotation: int, largeur_px: int = 320) -> bytes:
    """Petit rendu PNG (octets) de la page, pour l'aperçu du choix de page."""
    pymupdf = _pymupdf()
    pg = pymupdf.open(path)[page]
    r = pg.rect
    rot = int(rotation) % 360
    cote = r.width if rot in (0, 180) else r.height
    zoom = max(0.02, largeur_px / max(cote, 1.0))
    m = pymupdf.Matrix(zoom, zoom).prerotate(rot)
    return pg.get_pixmap(matrix=m, alpha=False).tobytes("png")


def titre_document(path: str) -> str:
    """Le titre déclaré dans les métadonnées du PDF, ou "" s'il n'y en a pas.

    Les plans du chantier en portent parfois un, plus parlant que le nom de
    fichier : le catalogue s'en sert comme titre par défaut."""
    try:
        meta = _pymupdf().open(path).metadata or {}
    except Exception:             # PDF illisible : le nom de fichier suffira
        return ""
    return str(meta.get("title") or "").strip()


def ranger_pdf(pdf_path: str, ship_folder: str) -> str:
    """Copie le PDF dans `<navire>/plans/` et rend le chemin de la copie.

    **Un navire est un dossier qu'on emporte tel quel** : le PDF du chantier
    doit voyager avec, sinon le re-rendu d'une page et la relecture des
    sommets pour l'accroche s'arrêtent au premier changement de machine. Un
    fichier déjà DANS le dossier du navire n'est pas recopié ; un homonyme de
    même taille est considéré comme le même plan. Si la copie échoue (dossier
    non inscriptible), on rend le chemin d'origine : mieux vaut un plan qui
    marche sur cette machine que pas de plan du tout.

    Une seule fonction pour les deux chemins qui rangent un PDF — l'import
    d'une page dans une vue (`import_into`) et l'entrée au catalogue
    (`catalogue_plans.ajouter`) — afin qu'ils ne puissent pas diverger."""
    import shutil
    plans = os.path.abspath(os.path.join(ship_folder, "plans"))
    src = os.path.abspath(pdf_path)
    ship = os.path.abspath(ship_folder)
    try:
        dedans = os.path.commonpath([src, ship]) == ship
    except ValueError:            # autre lecteur (Windows)
        dedans = False
    if dedans:
        return src
    dest = os.path.join(plans, os.path.basename(src))
    try:
        os.makedirs(plans, exist_ok=True)
        if not (os.path.exists(dest)
                and os.path.getsize(dest) == os.path.getsize(src)):
            shutil.copy2(src, dest)
    except OSError:
        return src
    return dest


def import_into(pdf_path: str, page: int, rotation: int, dpi: int,
                ship_folder: str):
    """Range un plan PDF dans le dossier du navire : copie du PDF dans
    `plans/` (s'il n'y est pas déjà — un navire est un dossier qu'on emporte
    tel quel, le re-rendu et l'accroche doivent y survivre) et rendu de la
    page en PNG à côté. Renvoie (chemin_png, chemin_pdf). Le PNG n'est refait
    que s'il manque ou s'il est plus vieux que le PDF."""
    plans = os.path.abspath(os.path.join(ship_folder, "plans"))
    os.makedirs(plans, exist_ok=True)
    src = os.path.abspath(pdf_path)
    dest_pdf = ranger_pdf(src, ship_folder)
    base = os.path.splitext(os.path.basename(src))[0]
    out = os.path.join(plans, f"{base}_p{int(page) + 1}_r{int(rotation) % 360}_{int(dpi)}dpi.png")
    if not (os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(dest_pdf)):
        render_page(dest_pdf, page, rotation, dpi, out)
    return out, dest_pdf


# ------------------------------------------------------------------ sommets
def _segments_et_sommets(page, full, x0, y0):
    """Sommets (N,2) et segments droits (M,4), en pixels image."""
    # Un plan d'ensemble compte 500 000 éléments : on n'y crée aucun objet
    # pymupdf, on aligne des flottants et on applique la matrice d'un coup
    # en numpy (sinon 7 s rien que pour convertir les points).
    seg_raw = []      # x1, y1, x2, y2 en coordonnées page (non tournées)
    pt_raw = []       # sommets isolés (extrémités de courbes)
    for path in page.get_drawings():
        for it in path["items"]:
            kind = it[0]
            if kind == "l":
                a, b = it[1], it[2]
                seg_raw.append((a.x, a.y, b.x, b.y))
            elif kind == "re":
                r = it[1]
                seg_raw.append((r.x0, r.y0, r.x1, r.y0))
                seg_raw.append((r.x1, r.y0, r.x1, r.y1))
                seg_raw.append((r.x1, r.y1, r.x0, r.y1))
                seg_raw.append((r.x0, r.y1, r.x0, r.y0))
            elif kind == "qu":
                q = it[1]
                c = (q.ul, q.ur, q.lr, q.ll)
                for i in range(4):
                    a, b = c[i], c[(i + 1) % 4]
                    seg_raw.append((a.x, a.y, b.x, b.y))
            elif kind == "c":
                # courbe de Bézier : seules les extrémités sont des sommets
                # sûrs (les points de contrôle ne sont pas sur le trait)
                pt_raw.append((it[1].x, it[1].y))
                pt_raw.append((it[4].x, it[4].y))
    S = np.asarray(seg_raw, dtype=np.float64).reshape(-1, 4)
    C = np.asarray(pt_raw, dtype=np.float64).reshape(-1, 2)

    def transformer(pts):
        # pymupdf : x' = a·x + c·y + e ; y' = b·x + d·y + f
        if len(pts) == 0:
            return pts.reshape(0, 2)
        out = np.empty_like(pts)
        out[:, 0] = full.a * pts[:, 0] + full.c * pts[:, 1] + full.e - x0
        out[:, 1] = full.b * pts[:, 0] + full.d * pts[:, 1] + full.f - y0
        return out

    if len(S):
        S = np.hstack([transformer(S[:, :2]), transformer(S[:, 2:])])
        P = np.vstack([S[:, :2], S[:, 2:], transformer(C)])
    else:
        P = transformer(C)
    return P, S


def intersections(segs: np.ndarray, cell: float = 48.0, voisins: int = 24,
                   max_segments: int = 400000) -> np.ndarray:
    """Croisements francs de segments droits, (K,2) pixels.

    On ne cherche que les croisements **à l'intérieur** des deux segments
    (les jonctions en T ou en L ont déjà leur sommet dans la liste des
    extrémités). Pour rester bon marché sur des centaines de milliers de
    traits, on range les segments dans des cases de `cell` pixels et on ne
    confronte qu'un segment aux `voisins` suivants de la même case, une fois
    triés par abscisse — dans une zone très dense (hachures) quelques
    croisements peuvent échapper, ce qui n'a aucune conséquence : ce ne sont
    pas des points qu'on cale.
    """
    if len(segs) == 0:
        return np.zeros((0, 2))
    S = segs[:max_segments]
    dx = S[:, 2] - S[:, 0]
    dy = S[:, 3] - S[:, 1]
    longueur = np.hypot(dx, dy)
    S = S[longueur > 0.5]
    if len(S) < 2:
        return np.zeros((0, 2))
    x_lo = np.floor(np.minimum(S[:, 0], S[:, 2]) / cell).astype(np.int64)
    x_hi = np.floor(np.maximum(S[:, 0], S[:, 2]) / cell).astype(np.int64)
    y_lo = np.floor(np.minimum(S[:, 1], S[:, 3]) / cell).astype(np.int64)
    y_hi = np.floor(np.maximum(S[:, 1], S[:, 3]) / cell).astype(np.int64)
    n_cells = (x_hi - x_lo + 1) * (y_hi - y_lo + 1)
    # un trait qui couvrirait des milliers de cases (cadre du plan) coûte
    # cher pour rien : on l'ignore pour les croisements
    garde = n_cells <= 4000
    S, x_lo, x_hi, y_lo, y_hi, n_cells = (
        S[garde], x_lo[garde], x_hi[garde], y_lo[garde], y_hi[garde], n_cells[garde])
    if len(S) < 2:
        return np.zeros((0, 2))
    seg_idx = np.repeat(np.arange(len(S)), n_cells)
    # numéro de case local dans le rectangle de cases de chaque segment
    offsets = np.arange(len(seg_idx)) - np.repeat(
        np.cumsum(n_cells) - n_cells, n_cells)
    largeur = np.repeat(x_hi - x_lo + 1, n_cells)
    cx = np.repeat(x_lo, n_cells) + offsets % largeur
    cy = np.repeat(y_lo, n_cells) + offsets // largeur
    # clé de case + abscisse de départ pour que les voisins soient proches
    cle = (cy - cy.min()) * (cx.max() - cx.min() + 2) + (cx - cx.min())
    ordre = np.lexsort((np.minimum(S[seg_idx, 0], S[seg_idx, 2]), cle))
    cle = cle[ordre]
    seg_idx = seg_idx[ordre]
    out = []
    n = len(seg_idx)
    for d in range(1, voisins + 1):
        if d >= n:
            break
        same = cle[:-d] == cle[d:]
        i = seg_idx[:-d][same]
        j = seg_idx[d:][same]
        if len(i) == 0:
            continue
        a = S[i]
        b = S[j]
        r_x, r_y = a[:, 2] - a[:, 0], a[:, 3] - a[:, 1]
        s_x, s_y = b[:, 2] - b[:, 0], b[:, 3] - b[:, 1]
        den = r_x * s_y - r_y * s_x
        ok = np.abs(den) > 1e-9
        if not ok.any():
            continue
        a, b = a[ok], b[ok]
        r_x, r_y, s_x, s_y, den = r_x[ok], r_y[ok], s_x[ok], s_y[ok], den[ok]
        qp_x = b[:, 0] - a[:, 0]
        qp_y = b[:, 1] - a[:, 1]
        t = (qp_x * s_y - qp_y * s_x) / den
        u = (qp_x * r_y - qp_y * r_x) / den
        # marge d'un demi-pixel aux extrémités : un croisement au bout d'un
        # trait est déjà un sommet
        la = np.hypot(r_x, r_y)
        lb = np.hypot(s_x, s_y)
        eps_a = 0.5 / la
        eps_b = 0.5 / lb
        inside = (t > eps_a) & (t < 1 - eps_a) & (u > eps_b) & (u < 1 - eps_b)
        if inside.any():
            out.append(np.column_stack([a[inside, 0] + t[inside] * r_x[inside],
                                        a[inside, 1] + t[inside] * r_y[inside]]))
    if not out:
        return np.zeros((0, 2))
    return np.vstack(out)


def _dedoublonner(P: np.ndarray, pas: float = 0.1) -> np.ndarray:
    if len(P) == 0:
        return P.reshape(0, 2)
    q = np.round(P / pas).astype(np.int64)
    _, idx = np.unique(q, axis=0, return_index=True)
    return P[np.sort(idx)]


def extract_vertices(path: str, page: int, rotation: int, dpi: int,
                     with_intersections: bool = True) -> np.ndarray:
    """Sommets (N,2) en pixels de l'image rendue par `render_page` avec les
    mêmes page / rotation / dpi. Hors de l'image (marges négatives) rien
    n'est gardé."""
    pg = _pymupdf().open(path)[page]
    full, x0, y0 = _matrice(pg, rotation, dpi)
    P, S = _segments_et_sommets(pg, full, x0, y0)
    if with_intersections and len(S):
        X = intersections(S)
        if len(X):
            P = np.vstack([P, X])
    P = _dedoublonner(P)
    w, h = taille_rendu(path, page, rotation, dpi)
    if len(P):
        garde = (P[:, 0] >= -1) & (P[:, 1] >= -1) & (P[:, 0] <= w + 1) & (P[:, 1] <= h + 1)
        P = P[garde]
    return np.ascontiguousarray(P, dtype=np.float64)


# ------------------------------------------------------------------ accroche
class SnapIndex:
    """Recherche du sommet le plus proche, en temps constant par requête.

    Les points sont rangés par case de `cell` pixels et triés par numéro de
    case : une requête ne lit que les cases couvertes par le rayon, par
    `searchsorted`, sans jamais parcourir la liste entière — c'est ce qui
    garde le déplacement de la souris fluide avec un million de sommets.
    """

    def __init__(self, points, cell: float = 64.0):
        P = np.asarray(points, dtype=np.float64).reshape(-1, 2)
        self.cell = float(cell)
        self.n = len(P)
        if self.n == 0:
            self.points = P
            self._cles = np.zeros(0, dtype=np.int64)
            self._x_min = self._y_min = 0
            self._largeur = self._hauteur = 1
            return
        cx = np.floor(P[:, 0] / self.cell).astype(np.int64)
        cy = np.floor(P[:, 1] / self.cell).astype(np.int64)
        self._x_min, self._y_min = int(cx.min()), int(cy.min())
        self._largeur = int(cx.max() - self._x_min) + 1
        self._hauteur = int(cy.max() - self._y_min) + 1
        cles = (cy - self._y_min) * self._largeur + (cx - self._x_min)
        ordre = np.argsort(cles, kind="stable")
        self.points = P[ordre]
        self._cles = cles[ordre]

    def __len__(self):
        return self.n

    def _cle(self, cx, cy):
        return (cy - self._y_min) * self._largeur + (cx - self._x_min)

    def nearest(self, x: float, y: float, radius: float, exclude=None):
        """(px, py, distance) du sommet le plus proche à moins de `radius`,
        ou None. `exclude` : point (u, v) à ignorer (sommet qu'on déplace)."""
        if self.n == 0 or radius <= 0:
            return None
        k = int(np.ceil(radius / self.cell))
        k = min(k, 12)      # très dézoomé : on se contente des cases voisines
        cx0 = int(np.floor(x / self.cell))
        cy0 = int(np.floor(y / self.cell))
        best = None
        best_d = radius
        for cy in range(cy0 - k, cy0 + k + 1):
            if cy < self._y_min or cy - self._y_min >= self._hauteur:
                continue
            lo = self._cle(cx0 - k, cy)
            hi = self._cle(cx0 + k, cy)
            i0 = int(np.searchsorted(self._cles, lo, side="left"))
            i1 = int(np.searchsorted(self._cles, hi, side="right"))
            if i1 <= i0:
                continue
            bloc = self.points[i0:i1]
            d = np.hypot(bloc[:, 0] - x, bloc[:, 1] - y)
            if exclude is not None:
                d = np.where((np.abs(bloc[:, 0] - exclude[0]) < 1e-6)
                             & (np.abs(bloc[:, 1] - exclude[1]) < 1e-6), np.inf, d)
            j = int(np.argmin(d))
            if d[j] < best_d:
                best_d = float(d[j])
                best = (float(bloc[j, 0]), float(bloc[j, 1]), best_d)
        return best


def snap(x: float, y: float, radius: float, indexes, exclude=None):
    """Le sommet le plus proche parmi plusieurs index (PDF, polygones, points
    de calage) — le plus près gagne, quelle que soit sa source."""
    best = None
    for idx in indexes:
        if idx is None or len(idx) == 0:
            continue
        r = idx.nearest(x, y, radius, exclude=exclude)
        if r is not None and (best is None or r[2] < best[2]):
            best = r
    return best


# ------------------------------------------------------------------ cache
_CACHE = {}
# la lecture des sommets tourne dans un fil de fond (voir `scene.ChargeurTraits`)
# pendant que l'interface interroge le même cache : un verrou, et personne ne
# voit un cache à moitié vidé
_VERROU = threading.Lock()


def _cle_cache(pdf_path, page, rotation, dpi):
    try:
        mtime = os.path.getmtime(pdf_path)
    except OSError:
        mtime = 0
    return (os.path.abspath(pdf_path), int(page), int(rotation) % 360, int(dpi), mtime)


def cle_cache(pdf_path, page, rotation, dpi):
    """Clé de session d'un index d'accroche. Même nom et même rôle que dans
    `dxf_plan` : l'éditeur manipule les deux sources sans savoir laquelle."""
    return _cle_cache(pdf_path, page, rotation, dpi)


def ranger_index(cle, index):
    """Range un index **fini**. Rien d'autre n'écrit dans le cache : c'est ce
    qui garantit qu'un index à moitié construit (lecture en fil de fond) ne
    peut jamais être servi à l'accroche."""
    if index is None:
        return
    with _VERROU:
        if len(_CACHE) >= 6:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[cle] = index


def snap_index_for(pdf_path: str, page: int, rotation: int, dpi: int) -> SnapIndex | None:
    """Index d'accroche d'une page rendue, mémorisé pour la session (la
    lecture d'un plan de 500 000 traits prend quelques secondes : on ne la
    refait pas à chaque changement de vue). None si le PDF a disparu."""
    if not pdf_path or not os.path.exists(pdf_path):
        return None
    cle = _cle_cache(pdf_path, page, rotation, dpi)
    with _VERROU:
        idx = _CACHE.get(cle)
    if idx is None:
        idx = SnapIndex(extract_vertices(pdf_path, page, rotation, dpi))
        ranger_index(cle, idx)
    return idx


def snap_index_cached(pdf_path: str, page: int, rotation: int, dpi: int):
    """L'index s'il est déjà en mémoire, sans rien lire."""
    if not pdf_path:
        return None
    with _VERROU:
        return _CACHE.get(_cle_cache(pdf_path, page, rotation, dpi))


def oublier_index():
    """Vide le cache de session (tests, ou plan remplacé à chaud)."""
    with _VERROU:
        _CACHE.clear()
