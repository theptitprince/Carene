# -*- coding: utf-8 -*-
"""Interpolation générique — aucune donnée navire ici, uniquement des utilitaires
numériques réutilisables pour lire les tables du navire virtuel.
"""
import bisect

import numpy as np


def interp1d_linear(xs, ys, xq, hors_bornes="prolonge"):
    """Interpolation linéaire 1D.

    Hors des bornes tabulées, le comportement est **explicite** :

    - ``"prolonge"`` (défaut) : prolongement linéaire par la pente du segment
      de bord. C'est ce que le nom de la fonction laissait entendre, mais pas
      ce qu'elle faisait : `np.interp` **écrête** silencieusement à la dernière
      valeur, ce qui rendait une valeur fausse sans le dire ;
    - ``"ecrete"`` : valeur du dernier point tabulé, comportement historique,
      à ne demander que là où il est justifié (tables de facteurs
      réglementaires bornées par le texte, par exemple) ;
    - ``"refuse"`` : lève une ValueError.

    Dans tous les cas, savoir si l'on est dans le domaine reste la
    responsabilité de l'appelant (voir `Grid2D.contains`, `Navire.domaine`) :
    une valeur prolongée n'a aucune portée réglementaire.
    """
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    if xs.size == 0:
        raise ValueError("interpolation sur une table vide")
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]
    if xs.size == 1:
        return float(ys[0])
    x = float(xq)
    if xs[0] <= x <= xs[-1] or hors_bornes == "ecrete":
        return float(np.interp(x, xs, ys))
    if hors_bornes == "refuse":
        raise ValueError(f"{x:g} hors du domaine tabulé "
                         f"[{xs[0]:g}, {xs[-1]:g}]")
    if x < xs[0]:
        pente = (ys[1] - ys[0]) / (xs[1] - xs[0])
        return float(ys[0] + pente * (x - xs[0]))
    pente = (ys[-1] - ys[-2]) / (xs[-1] - xs[-2])
    return float(ys[-1] + pente * (x - xs[-1]))


def _pchip_slopes(xs, ys):
    """Pentes de Fritsch-Carlson pour une cubique d'Hermite monotone (PCHIP),
    ré-implémentées ici pour ne pas dépendre de scipy (moteur volontairement
    léger / portable)."""
    n = len(xs)
    if n < 2:
        raise ValueError("PCHIP demande au moins deux points ; "
                         f"la table n'en a que {n}")
    h = np.diff(xs)
    if np.any(h <= 0):
        # abscisses dupliquées : la division par h donnerait des NaN qui se
        # propageraient jusqu'aux critères sans lever la moindre erreur
        raise ValueError("PCHIP demande des abscisses strictement "
                         "croissantes (doublon dans la table)")
    delta = np.diff(ys) / h
    d = np.zeros(n)
    if n == 2:
        d[:] = delta[0]
        return d
    for i in range(1, n - 1):
        if delta[i - 1] * delta[i] <= 0:
            d[i] = 0.0
        else:
            w1 = 2 * h[i] + h[i - 1]
            w2 = h[i] + 2 * h[i - 1]
            d[i] = (w1 + w2) / (w1 / delta[i - 1] + w2 / delta[i])
    # extrémités (formule non centrée de PCHIP standard)
    d[0] = _pchip_end(h[0], h[1] if n > 2 else h[0], delta[0], delta[1] if n > 2 else delta[0])
    d[-1] = _pchip_end(h[-1], h[-2] if n > 2 else h[-1], delta[-1], delta[-2] if n > 2 else delta[-1])
    return d


def _pchip_end(h0, h1, delta0, delta1):
    d = ((2 * h0 + h1) * delta0 - h0 * delta1) / (h0 + h1)
    if d * delta0 <= 0:
        d = 0.0
    elif delta0 * delta1 <= 0 and abs(d) > abs(3 * delta0):
        d = 3 * delta0
    return d


def pchip_eval(xs, ys, xq):
    """Évalue la cubique d'Hermite monotone PCHIP(xs, ys) en xq (scalaire ou
    tableau). Extrapolation linéaire hors bornes."""
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]
    d = _pchip_slopes(xs, ys)      # lève si table trop courte ou doublonnée
    scalar = np.isscalar(xq)
    xq_arr = np.atleast_1d(np.asarray(xq, dtype=float))
    out = np.empty_like(xq_arr)
    n = len(xs)
    for j, x in enumerate(xq_arr):
        if x <= xs[0]:
            out[j] = ys[0] + d[0] * (x - xs[0])
            continue
        if x >= xs[-1]:
            out[j] = ys[-1] + d[-1] * (x - xs[-1])
            continue
        i = bisect.bisect_right(xs, x) - 1
        i = min(max(i, 0), n - 2)
        h = xs[i + 1] - xs[i]
        t = (x - xs[i]) / h
        t2, t3 = t * t, t * t * t
        h00 = 2 * t3 - 3 * t2 + 1
        h10 = t3 - 2 * t2 + t
        h01 = -2 * t3 + 3 * t2
        h11 = t3 - t2
        out[j] = (h00 * ys[i] + h10 * h * d[i] + h01 * ys[i + 1] + h11 * h * d[i + 1])
    return float(out[0]) if scalar else out


class Grid2D:
    """Table 2D navire (ex : hydrostatiques, pantocarènes) organisée en lignes
    d'assiette ("axis1"), chaque ligne portant son propre axe secondaire (tirant
    d'eau ou déplacement) et un jeu de colonnes de valeurs. Interpolation
    bilinéaire (linéaire sur l'axe secondaire dans chaque ligne encadrante, puis
    linéaire entre les deux lignes) : robuste même si l'axe secondaire n'a pas
    exactement les mêmes valeurs d'une ligne à l'autre (bruit d'extraction PDF).
    """

    def __init__(self, axis1_values, rows_axis2, rows_values):
        """axis1_values : liste triée des N valeurs d'assiette.
        rows_axis2 : liste de N tableaux (axe secondaire, ex tirant d'eau).
        rows_values : liste de N dict{colonne: tableau de valeurs}, mêmes clés
        pour toutes les lignes."""
        order = np.argsort(axis1_values)
        self.axis1 = np.asarray(axis1_values, dtype=float)[order]
        self.rows_axis2 = [np.asarray(rows_axis2[i], dtype=float) for i in order]
        self.rows_values = [rows_values[i] for i in order]
        self.columns = list(self.rows_values[0].keys())

    def _row_interp(self, i, x2, col, method):
        xs = self.rows_axis2[i]
        ys = np.asarray(self.rows_values[i][col], dtype=float)
        if method == "pchip":
            return pchip_eval(xs, ys, x2)
        return interp1d_linear(xs, ys, x2)

    def value(self, x1, x2, col, method="linear"):
        a1 = self.axis1
        n = len(a1)
        i = int(np.searchsorted(a1, x1))
        i = min(max(i, 1), n - 1)
        i0, i1 = i - 1, i
        v0 = self._row_interp(i0, x2, col, method)
        v1 = self._row_interp(i1, x2, col, method)
        if a1[i1] == a1[i0]:
            return v0
        t = (x1 - a1[i0]) / (a1[i1] - a1[i0])
        return v0 + t * (v1 - v0)

    def row_at(self, x1, x2, method="linear"):
        """Toutes les colonnes interpolées à (x1, x2)."""
        return {c: self.value(x1, x2, c, method) for c in self.columns}

    def bounds(self, x1=None):
        """((min, max) axe 1, (min, max) axe 2).

        Les bornes de l'axe 2 sont celles de la ligne encadrante la plus
        restrictive : hors de cet intervalle, `value` extrapole, et une
        extrapolation de table hydrostatique n'a aucune valeur réglementaire.
        """
        a1 = (float(self.axis1[0]), float(self.axis1[-1]))
        if x1 is None:
            lo = max(float(r[0]) for r in self.rows_axis2)
            hi = min(float(r[-1]) for r in self.rows_axis2)
            return a1, (lo, hi)
        i = int(np.searchsorted(self.axis1, x1))
        i = min(max(i, 1), len(self.axis1) - 1)
        rows = (self.rows_axis2[i - 1], self.rows_axis2[i])
        return a1, (max(float(r[0]) for r in rows),
                    min(float(r[-1]) for r in rows))

    def contains(self, x1, x2, tol=1e-9):
        # bool() explicite : les comparaisons numpy renvoient un np.bool_, qui
        # échoue aux tests d'identité (`is True` / `is False`) côté appelant.
        (t0, t1), (d0, d1) = self.bounds(x1)
        return bool(t0 - tol <= float(x1) <= t1 + tol
                    and d0 - tol <= float(x2) <= d1 + tol)
