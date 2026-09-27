# -*- coding: utf-8 -*-
"""Les formes de la carène, décalquées sur le plan des formes du chantier.

Lecture seule de `formes.json` : un tableau de demi-sections transversales,
une par station tracée, avec l'abscisse de la station dans le repère du
dossier (origine C.0, D-11).

**Ce module ne sert jamais au calcul de stabilité** (D-10). Il sert à
dessiner : la silhouette de profil, les coupes transversales, la vue iso —
et, le cas échéant, à situer une pose. Le déplacement, le GM et les GZ
restent sur les tables du dossier approuvé, quoi que dise cette coque.

Le format est une donnée du navire, pas une constante de code : tout ce que
le module sait d'un navire est dans son `formes.json`, y compris ce que le
décalquage n'a pas pu lire (`messages`).

Sans Qt, sans autre entrée-sortie que la lecture du dossier du navire.
"""
from __future__ import annotations

import json
import os
from bisect import bisect_left

NOM_FICHIER = "formes.json"
_N_ECHANTILLONS = 60          # points d'une demi-section rendue


def charger(dossier: str) -> "Formes | None":
    """Formes du navire, ou None si le fichier est absent ou illisible.

    Illisible veut dire : JSON cassé, format inconnu, moins de deux stations
    exploitables. On ne devine pas une carène à partir d'un fichier douteux —
    mieux vaut ne rien dessiner (D-10)."""
    if not dossier:
        return None
    chemin = os.path.join(dossier, NOM_FICHIER)
    try:
        with open(chemin, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    brut = d.get("stations")
    if not isinstance(brut, list):
        return None
    stations = []
    for s in brut:
        try:
            x = float(s["x_m"])
            pts = [(float(y), float(z)) for y, z in s["demi_section"]]
        except (KeyError, TypeError, ValueError):
            continue
        pts = [(y, z) for y, z in pts]
        if len(pts) < 2:
            continue
        pts.sort(key=lambda p: p[1])
        stations.append((x, s.get("n"), pts))
    if len(stations) < 2:
        return None
    stations.sort(key=lambda t: t[0])
    return Formes(d, stations)


class Formes:
    """Les demi-sections décalquées, et de quoi les interpoler.

    `stations` : abscisses croissantes dans le repère du dossier (m depuis
    C.0). `source` : le plan d'où elles sortent. `messages` : ce qui a été
    supposé ou n'a pas pu être lu, dit en toutes lettres — à afficher, pas à
    cacher."""

    def __init__(self, donnees, stations):
        self._d = donnees
        self._x = [t[0] for t in stations]
        self._n = [t[1] for t in stations]
        self._pts = [t[2] for t in stations]
        self.stations = list(self._x)
        self.source = str(donnees.get("source", ""))
        self.messages = [str(m) for m in donnees.get("messages", [])]

    # ------------------------------------------------------------- accès
    @property
    def x_min(self) -> float:
        return self._x[0]

    @property
    def x_max(self) -> float:
        return self._x[-1]

    def numeros(self) -> list:
        """Numéro de section du plan, quand il est connu (sinon None)."""
        return list(self._n)

    # --------------------------------------------------- interpolation
    @staticmethod
    def _echantillonner(pts, n=_N_ECHANTILLONS):
        """Rééchantillonne une demi-section à `n` points, à pas d'abscisse
        curviligne constant. C'est ce qui permet de mélanger deux sections
        de formes différentes sans écraser le bouchain : un point donné du
        rendu correspond au même endroit du parcours quille → livet."""
        long = [0.0]
        for (y0, z0), (y1, z1) in zip(pts, pts[1:]):
            long.append(long[-1] + ((y1 - y0) ** 2 + (z1 - z0) ** 2) ** 0.5)
        total = long[-1]
        if total <= 0:
            return [pts[0]] * n
        out = []
        j = 0
        for k in range(n):
            cible = total * k / (n - 1)
            while j < len(long) - 2 and long[j + 1] < cible:
                j += 1
            d = long[j + 1] - long[j]
            t = 0.0 if d <= 0 else (cible - long[j]) / d
            y = pts[j][0] + t * (pts[j + 1][0] - pts[j][0])
            z = pts[j][1] + t * (pts[j + 1][1] - pts[j][1])
            out.append((y, z))
        return out

    def demi_section(self, x: float) -> list:
        """Demi-section tribord (y <= 0) de la quille au livet, interpolée
        entre les deux stations voisines. [] hors de la carène."""
        if not self._x or x < self._x[0] - 1e-9 or x > self._x[-1] + 1e-9:
            return []
        i = bisect_left(self._x, x)
        if i <= 0:
            return [(round(y, 4), round(z, 4)) for y, z in self._pts[0]]
        if i >= len(self._x):
            return [(round(y, 4), round(z, 4)) for y, z in self._pts[-1]]
        if abs(self._x[i] - x) < 1e-9:
            return [(round(y, 4), round(z, 4)) for y, z in self._pts[i]]
        x0, x1 = self._x[i - 1], self._x[i]
        t = (x - x0) / (x1 - x0)
        a = self._echantillonner(self._pts[i - 1])
        b = self._echantillonner(self._pts[i])
        return [(round(p[0] + t * (q[0] - p[0]), 4),
                 round(p[1] + t * (q[1] - p[1]), 4)) for p, q in zip(a, b)]

    def section(self, x: float) -> list:
        """Section complète, bâbord et tribord, fermée sur la quille.

        Le contour part du livet tribord, descend jusqu'à la quille, passe
        de l'autre côté et remonte au livet bâbord. Il se referme sur la
        quille : le point le plus bas est commun aux deux moitiés quand la
        carène y est pointue, et la sole les relie quand elle est plate."""
        demi = self.demi_section(x)
        if not demi:
            return []
        tribord = list(reversed(demi))              # livet → quille
        babord = [(-y, z) for y, z in demi]         # quille → livet
        if abs(tribord[-1][0]) < 1e-9 and abs(babord[0][0]) < 1e-9:
            babord = babord[1:]                     # quille pointue : un seul point
        return tribord + babord

    # -------------------------------------------------------- mesures
    def largeur_max_m(self) -> float:
        """Largeur hors membres maximale de la carène décalquée (m)."""
        return 2.0 * max((abs(y) for pts in self._pts for y, _z in pts), default=0.0)

    def livet(self) -> list:
        """Ligne de pont (x, z) le long du navire, pour la vue de profil.

        Un point par station : le plus haut de chaque demi-section, c'est-à-
        dire le livet — pont principal au milieu, dunette à l'arrière."""
        return [(x, max(z for _y, z in pts)) for x, pts in zip(self._x, self._pts)]
