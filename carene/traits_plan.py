# -*- coding: utf-8 -*-
"""Les sommets accrochables d'un plan, rangés AVEC le navire.

Le curseur du décalquage s'accroche aux traits du plan de fond quand celui-ci
est vectoriel (PDF ou DXF). Mais le PDF du chantier ne voyage pas avec le
navire : il est lourd, il n'appartient pas au bord, et il est souvent dans un
dossier d'import qu'on ne livre pas. Sans lui, une cale décalquée à Concarneau
se retouchait à bord **sans la moindre accroche** — c'est ce qu'a constaté le
bord en voulant reprendre un contour.

Les sommets, eux, tiennent en un fichier de quelques mégaoctets. On les écrit
donc à côté de l'image rendue, une fois pour toutes, à la première lecture :
`plans/<image>.traits.npz`. Le PDF absent, l'accroche est toujours là.

Ce module offre la **même façade** que `pdf_plan` et `dxf_plan`
(`extract_vertices`, `snap_index_for`, `snap_index_cached`, `cle_cache`,
`ranger_index`), pour que `scene.source_traits` puisse le substituer sans que
le reste de l'interface s'en aperçoive.
"""
from __future__ import annotations

import os
import threading

import numpy as np

from .pdf_plan import SnapIndex

SUFFIXE = ".traits.npz"

_CACHE = {}
_VERROU = threading.Lock()


def chemin_traits(image_path: str) -> str:
    """Le fichier de sommets qui va avec cette image rendue."""
    if not image_path:
        return ""
    base, _ext = os.path.splitext(image_path)
    return base + SUFFIXE


def existe(image_path: str) -> bool:
    c = chemin_traits(image_path)
    return bool(c) and os.path.exists(c)


def sauver(image_path: str, points) -> str | None:
    """Écrit les sommets à côté de l'image. Rend le chemin, ou None si on n'a
    pas pu (dossier en lecture seule, image sans dossier) — l'accroche
    marche quand même pour la session, on ne casse rien."""
    c = chemin_traits(image_path)
    if not c:
        return None
    P = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    try:
        np.savez_compressed(c, points=P)
    except OSError:
        return None
    return c


def extract_vertices(chemin: str):
    """Les sommets, tels qu'ils ont été écrits."""
    with np.load(chemin) as f:
        return np.asarray(f["points"], dtype=np.float64)


def cle_cache(chemin: str):
    try:
        st = os.stat(chemin)
        return ("traits", os.path.abspath(chemin), int(st.st_mtime), st.st_size)
    except OSError:
        return ("traits", os.path.abspath(chemin), 0, 0)


def ranger_index(cle, index):
    with _VERROU:
        if len(_CACHE) >= 6:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[cle] = index


def snap_index_cached(chemin: str):
    with _VERROU:
        return _CACHE.get(cle_cache(chemin))


def snap_index_for(chemin: str):
    idx = snap_index_cached(chemin)
    if idx is None:
        idx = SnapIndex(extract_vertices(chemin))
        ranger_index(cle_cache(chemin), idx)
    return idx


def oublier():
    with _VERROU:
        _CACHE.clear()
