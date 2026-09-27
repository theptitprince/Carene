# -*- coding: utf-8 -*-
"""Modèle de données v2 : profil + ponts + capacités 3D, sérialisation JSON."""
from __future__ import annotations
from .ecriture import ecriture_atomique

import json
import os
from dataclasses import dataclass, field

from .core.stowage import rect_epontille
from .geometry import (Calibration, TOLERANCE_RECOUVREMENT_M,
                       profondeur_recouvrement)

KIND_CAPACITY = "CAPACITE"
KIND_CONTOUR = "CONTOUR"   # contour du pont (plaque) : sert à l'iso et au décor


@dataclass
class Calibrated:
    """Une image de plan et son calage dans le repère navire.

    axes : ("X","Z") pour le profil, ("X","Y") pour un plan de pont.

    Quand l'image vient d'un PDF vectoriel ou d'un DXF (D-9), on garde d'où
    elle sort — fichier, page/calques, rotation, résolution — pour pouvoir la
    rendre à nouveau (image effacée, dossier déplacé) et relire les sommets
    des traits pour l'accroche du curseur. L'image rendue reste la référence
    des pixels : tout ce qui est en aval (calage, tracés, chargement) ne voit
    qu'elle.

    Pour un DXF, `dxf_origin` (coordonnées DXF du coin haut-gauche de l'image)
    et `dxf_resolution` (pixels par unité de dessin) sont la transformation
    pixel ↔ dessin : les mémoriser fait retomber un re-rendu **exactement** sur
    les mêmes pixels, donc calage et tracés y survivent.
    """

    image_path: str = ""
    axes: tuple = ("X", "Z")
    calibration: Calibration = field(default_factory=Calibration)
    cal_points: list = field(default_factory=list)  # [{"pixel":[u,v], "real":[a,b]}]
    pdf_path: str = ""
    pdf_page: int = 0          # numéro de page, à partir de 0
    pdf_rotation: int = 0      # 0 / 90 / 180 / 270, en plus de la rotation propre
    pdf_dpi: int = 200
    dxf_path: str = ""
    dxf_layers: list = field(default_factory=list)   # calques rendus ([] = tous)
    dxf_origin: tuple = (0.0, 0.0)   # coin haut-gauche de l'image, en unités DXF
    dxf_resolution: float = 1.0      # pixels par unité de dessin
    dxf_size: tuple = (0, 0)         # taille du rendu, en pixels
    # Traits de construction : les lignes qu'on tire soi-même pour décalquer —
    # ligne de foi, couples, cotes reportées. Ce sont des repères de DESSIN,
    # pas de la géométrie du navire : rien en aval ne les lit, seule
    # l'accroche du curseur s'en sert. Forme : {"axe": "X"|"Y"|"Z",
    # "valeur": float, "libelle": str}.
    traits: list = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return bool(self.image_path) and self.calibration.valid

    @property
    def from_pdf(self) -> bool:
        return bool(self.pdf_path)

    @property
    def from_dxf(self) -> bool:
        return bool(self.dxf_path)

    @property
    def from_vector(self) -> bool:
        """Le fond vient d'un fichier vectoriel : ses traits sont accrochables."""
        return bool(self.pdf_path) or bool(self.dxf_path)

    @property
    def dxf_calques(self):
        """Les calques retenus, ou None pour « tout le dessin » — c'est la
        forme qu'attendent `dxf_plan.rendre` et `dxf_plan.extract_vertices`."""
        return list(self.dxf_layers) if self.dxf_layers else None

    def copy(self) -> "Calibrated":
        """Copie indépendante (même image, même calage) — pour un pont dessiné
        sur la même feuille qu'un autre."""
        return Calibrated(
            image_path=self.image_path, axes=tuple(self.axes),
            calibration=Calibration(self.calibration.M.copy())
            if self.calibration.valid else Calibration(),
            cal_points=[{k: (list(v) if isinstance(v, (list, tuple)) else v)
                         for k, v in p.items()} for p in self.cal_points],
            pdf_path=self.pdf_path, pdf_page=self.pdf_page,
            pdf_rotation=self.pdf_rotation, pdf_dpi=self.pdf_dpi,
            dxf_path=self.dxf_path, dxf_layers=list(self.dxf_layers),
            dxf_origin=tuple(self.dxf_origin),
            dxf_resolution=self.dxf_resolution,
            dxf_size=tuple(self.dxf_size),
            traits=[dict(t) for t in self.traits])

    def residuals(self):
        """Écart (m) de chaque point de calage une fois le calage appliqué —
        vide si le plan n'est pas calé."""
        if not self.calibration.valid or not self.cal_points:
            return []
        return self.calibration.residuals([p["pixel"] for p in self.cal_points],
                                          [p["real"] for p in self.cal_points])

    @property
    def est_vectoriel(self) -> bool:
        """Le fond vient d'un PDF ou d'un DXF : une seule échelle, axes à
        l'équerre — deux points sur la ligne de foi le calent (D-56)."""
        return bool(self.pdf_path or self.dxf_path)

    def to_dict(self):
        d = {
            "image_path": self.image_path,
            "axes": list(self.axes),
            "calibration": self.calibration.to_list(),
            "cal_points": self.cal_points,
        }
        if self.pdf_path:
            d.update(pdf_path=self.pdf_path, pdf_page=int(self.pdf_page),
                     pdf_rotation=int(self.pdf_rotation), pdf_dpi=int(self.pdf_dpi))
        if self.dxf_path:
            d.update(dxf_path=self.dxf_path, dxf_layers=list(self.dxf_layers),
                     dxf_origin=[float(self.dxf_origin[0]), float(self.dxf_origin[1])],
                     dxf_resolution=float(self.dxf_resolution),
                     dxf_size=[int(self.dxf_size[0]), int(self.dxf_size[1])])
        if self.traits:
            d["traits"] = [dict(t) for t in self.traits]
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(
            image_path=d.get("image_path", ""),
            axes=tuple(d.get("axes", ["X", "Z"])),
            calibration=Calibration.from_list(d.get("calibration")),
            cal_points=d.get("cal_points", []),
            pdf_path=d.get("pdf_path", "") or "",
            pdf_page=int(d.get("pdf_page", 0) or 0),
            pdf_rotation=int(d.get("pdf_rotation", 0) or 0),
            pdf_dpi=int(d.get("pdf_dpi", 200) or 200),
            dxf_path=d.get("dxf_path", "") or "",
            dxf_layers=list(d.get("dxf_layers") or []),
            dxf_origin=tuple(d.get("dxf_origin") or (0.0, 0.0)),
            dxf_resolution=float(d.get("dxf_resolution", 1.0) or 1.0),
            dxf_size=tuple(d.get("dxf_size") or (0, 0)),
            traits=[dict(t) for t in (d.get("traits") or [])],
        )

    # chemins relatifs au dossier du navire dans le JSON, absolus en mémoire
    def _relativize(self, d, base, rel):
        d["image_path"] = rel(self.image_path, base)
        if self.pdf_path:
            d["pdf_path"] = rel(self.pdf_path, base)
        if self.dxf_path:
            d["dxf_path"] = rel(self.dxf_path, base)

    def _absolutize(self, base):
        for attr in ("image_path", "pdf_path", "dxf_path"):
            p = getattr(self, attr)
            if p and not os.path.isabs(p):
                # un dossier écrit sous Windows porte « plans\\x.png » : relu
                # sous Linux ou macOS, l'antislash n'est pas un séparateur et
                # le plan serait « introuvable » alors qu'il est là
                p = p.replace("\\", "/")
                setattr(self, attr, os.path.normpath(os.path.join(base, p)))


@dataclass
class PalletLayout:
    """Plan de chargement en palettes d'une capacité : une grille de cellules
    (repérée en coordonnées navire, alignée X/Y) où chaque cellule porte un
    nombre de couches empilées. Les dimensions/poids de palette sont ceux de
    CE chargement (pas une donnée navire) — modifiables à volonté.
    """

    pallet_l: float = 1.2    # dimension le long de X (m)
    pallet_w: float = 1.0    # dimension le long de Y (m)
    pallet_h: float = 1.0    # hauteur d'une couche empilée (m)
    pallet_weight: float = 1.0   # t par palette
    cells: dict = field(default_factory=dict)   # "i,j" -> nb de couches (>0)

    def to_dict(self):
        return {
            "pallet_l": self.pallet_l, "pallet_w": self.pallet_w,
            "pallet_h": self.pallet_h, "pallet_weight": self.pallet_weight,
            "cells": {k: v for k, v in self.cells.items() if v > 0},
        }

    @classmethod
    def from_dict(cls, d):
        if not d:
            return None
        return cls(
            pallet_l=float(d.get("pallet_l", 1.2)), pallet_w=float(d.get("pallet_w", 1.0)),
            pallet_h=float(d.get("pallet_h", 1.0)),
            pallet_weight=float(d.get("pallet_weight", 1.0)),
            cells={k: int(v) for k, v in d.get("cells", {}).items() if int(v) > 0},
        )

    def totals(self, origin_x, origin_y, z_min):
        """(poids_t, lcg_m, tcg_m, vcg_m, nb_palettes) pondérés sur toutes les
        cellules occupées ; nul si aucune palette n'est placée. `origin_x/y` :
        coin bas-gauche de la grille en coordonnées navire (voir
        `Capacity.pallet_grid_origin`)."""
        w = lm = tm = vm = 0.0
        n = 0
        for key, count in self.cells.items():
            if count <= 0:
                continue
            i, j = (int(v) for v in key.split(","))
            cx = origin_x + (i + 0.5) * self.pallet_l
            cy = origin_y + (j + 0.5) * self.pallet_w
            cz = z_min + count * self.pallet_h / 2
            cw = count * self.pallet_weight
            w += cw
            lm += cw * cx
            tm += cw * cy
            vm += cw * cz
            n += count
        if w <= 0:
            return 0.0, 0.0, 0.0, 0.0, 0
        return w, lm / w, tm / w, vm / w, n


def epontille_fixe(e) -> bool:
    """Une épontille est fixe si sa fiche le dit ; les fiches d'avant la
    v2.14.3 n'ont pas la clé : elles sont amovibles, comme elles l'étaient."""
    return bool((e or {}).get("fixe", False))


@dataclass
class Capacity:
    """Capacité (ou contour de pont) : polygone X-Y sur un pont + étendue verticale.

    `points` en coordonnées NAVIRE (m). Y positif bâbord (convention du navire de référence).
    """

    code: str
    name: str = ""
    points: list = field(default_factory=list)   # [(x, y), ...]
    z_min: float = 0.0
    z_max: float = 0.0
    fill: float = 0.0
    kind: str = KIND_CAPACITY
    pallet: "PalletLayout | None" = None   # plan de chargement palettes (le cas échéant)
    # Plan propre à CETTE capacité (vue de dessus calée en X-Y). Facultatif :
    # quand il existe, il sert de fond au placement des palettes à la place du
    # plan du pont — utile quand plusieurs cales partagent un même pont et
    # qu'on veut travailler sur un plan de cale à plus grande échelle.
    plan: "Calibrated | None" = None
    # charge de pont admissible (t/m²) ; 0 = non renseignée, non contrainte
    charge_admissible_t_m2: float = 0.0
    # Zones interdites dans la cale : épontilles, descentes, puits… — une cale
    # n'est pas forcément entièrement utilisable, même de forme simple.
    # Liste de rectangles [x0, y0, x1, y1, nom] en repère navire.
    obstacles: list = field(default_factory=list)
    # Zones où la charge admissible diffère de celle de la cale : calque posé
    # sur le plan, NON bloquant — une charge qui dépasse est signalée, pas
    # refusée (la limite vient d'un tracé, pas d'un chiffre du dossier).
    # Liste de dicts {"nom", "t_m2", "points": [(x, y), ...]}.
    zones_charge: list = field(default_factory=list)
    # ÉPONTILLES AMOVIBLES : leurs emplacements, tracés une fois pour toutes
    # dans l'éditeur de plans. Le manuel d'assujettissement (§ *Removable
    # pillars*) dit où elles peuvent aller — cales avant et
    # arrière de tous les ponts, jamais la cave — et ce qu'elles tiennent
    # (MSL 50 kN), pas leurs coordonnées : c'est le bord qui les place.
    #
    # Ce ne sont PAS des `obstacles` : un obstacle est de la structure, il est
    # toujours là. Une épontille se pose et se dépose à chaque escale ; savoir
    # laquelle est en place est une décision du POINT
    # (`LoadingCondition.epontilles_en_place`), pas une donnée du navire.
    #
    # [{"id", "nom", "x", "y", "largeur_m", "longueur_m", "note", "fixe"}] —
    # `x`/`y` au CENTRE, `longueur_m` selon X, `largeur_m` selon Y, `id`
    # STABLE parce que le chargement s'y réfère. `fixe` (défaut False) : une
    # épontille FIXE est de la structure — toujours en place, jamais déposée
    # (le bord l'a voulue ainsi : un seul outil « Épontille », et une case
    # « fixe » sur la fiche, plutôt qu'un rectangle à part qui ne posait rien
    # pour un poteau de 0,2 m).
    epontilles: list = field(default_factory=list)
    # VERROUS (v2.14.10, retour du bord). Un plan se décalque puis se retouche
    # pendant des semaines, et rien n'empêchait de décaler une cale entière
    # d'un glisser malheureux. Deux niveaux, et rien de plus :
    #   `verrouillee`         : la cale ne bouge plus du tout — ni ses sommets,
    #                           ni son contour, on n'en ajoute ni n'en retire ;
    #   `sommets_verrouilles` : les INDICES des sommets figés un par un, pour
    #                           tenir un coin sur un couple sans figer le reste.
    # C'est une donnée du NAVIRE, pas un réglage de poste (D-42) : un plan
    # verrouillé l'est pour tous ceux qui ouvrent le dossier. Un fichier
    # d'avant ne porte aucune des deux clés : rien n'y est verrouillé.
    verrouillee: bool = False
    sommets_verrouilles: list = field(default_factory=list)
    # ANCIENS CODES (2.20.1). Les points du journal rangent leurs colis sous
    # le CODE de la cale. Renommer une cale laissait donc sa cargaison sans
    # cale — « cale inconnue », comptée à la quille : 1,0 m de GM en trop
    # sur 200 t, sans un mot. La cale garde désormais la liste des codes
    # qu'elle a portés, et un colis rangé sous l'un d'eux reste dans CETTE
    # cale, à SA hauteur, dans tous les points — figés compris, qu'on ne
    # réécrit pas.
    anciens_codes: list = field(default_factory=list)
    # LES CLASSES IMDG ADMISES (D-83), une donnée du navire posée dans
    # l'éditeur de plans : [] = aucune marchandise dangereuse (le cas de
    # presque toutes les cales) ; ["toutes"] ; ou les classes (« 3 », « 9 »).
    classes_imdg: list = field(default_factory=list)

    # ---------------------------------------------------------------- verrous
    def sommet_verrouille(self, i: int) -> bool:
        """Ce sommet est-il figé ? Une cale verrouillée fige TOUS les siens."""
        return bool(self.verrouillee) or int(i) in set(self.sommets_verrouilles)

    def verrouiller_sommet(self, i: int, on: bool = True):
        """Fige ou libère le sommet n°`i`.

        La liste reste triée et sans doublon : elle est relue telle quelle par
        le dessin, par l'arbre et par le fichier du navire."""
        v = {int(k) for k in self.sommets_verrouilles}
        if on:
            v.add(int(i))
        else:
            v.discard(int(i))
        self.sommets_verrouilles = sorted(k for k in v if 0 <= k < len(self.points))

    def inserer_sommet(self, index: int, point):
        """Insère un sommet AVANT `index` et fait suivre les verrous.

        Tout l'intérêt d'un verrou est de tenir un sommet PRÉCIS : insérer un
        sommet avant lui décale son indice, et un verrou resté sur l'ancien
        numéro figerait le voisin — exactement le contraire de ce qui a été
        demandé."""
        index = max(0, min(int(index), len(self.points)))
        self.points.insert(index, point)
        self.sommets_verrouilles = sorted(k + 1 if k >= index else k
                                          for k in self.sommets_verrouilles)

    def supprimer_sommet(self, index: int):
        """Retire le sommet `index` : son verrou part avec lui, ceux d'après
        reculent d'un cran."""
        index = int(index)
        if not 0 <= index < len(self.points):
            return
        del self.points[index]
        self.sommets_verrouilles = sorted(k - 1 if k > index else k
                                          for k in self.sommets_verrouilles
                                          if k != index)

    @property
    def x_range(self):
        if not self.points:
            return (0.0, 0.0)
        xs = [p[0] for p in self.points]
        return (min(xs), max(xs))

    def pallet_grid_origin(self):
        """Coin bas-gauche (X min, Y min) de la grille de palettes — ancré au
        rectangle englobant du polygone de la capacité."""
        if not self.points:
            return (0.0, 0.0)
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return (min(xs), min(ys))

    def obstacles_actifs(self, epontilles_en_place=()):
        """Ce qui INTERDIT la pose dans cette cale, ici et maintenant.

        La structure permanente (`obstacles`) et, en plus, les épontilles que
        l'officier a effectivement mises en place à ce point. Une épontille
        non posée ne contraint rien : on doit pouvoir voir son emplacement
        sans que le logiciel refuse d'y poser quoi que ce soit."""
        out = [list(o) for o in self.obstacles]
        ids = set(epontilles_en_place or ())
        for e in self.epontilles:
            if epontille_fixe(e) or e.get("id") in ids:
                out.append(list(rect_epontille(e)))
        return out

    def epontilles_fixes(self):
        """Les identifiants des épontilles fixes de cette cale : toujours en
        place, quel que soit le point de chargement."""
        return {e.get("id") for e in self.epontilles if epontille_fixe(e)}

    def epontille(self, eid):
        """L'épontille de cet identifiant dans cette cale, ou None."""
        return next((e for e in self.epontilles if e.get("id") == eid), None)

    def nouvel_id_epontille(self) -> str:
        """Un identifiant neuf et STABLE, du genre « CALE2-E3 ».

        Il porte le code de la cale : le chargement range les épontilles en
        place à plat, sans dire de quelle cale elles viennent, et deux cales
        ne doivent jamais se marcher dessus."""
        pris = {e.get("id") for e in self.epontilles}
        n = len(self.epontilles) + 1
        while f"{self.code}-E{n}" in pris:
            n += 1
        return f"{self.code}-E{n}"

    def to_dict(self):
        # `pallet` n'est volontairement PAS écrit ici : un plan de palettes
        # appartient à une condition de chargement, pas à la géométrie du
        # navire (voir carene.condition_model). `from_dict` le relit quand
        # même, pour récupérer les fichiers des versions antérieures.
        d = {
            "code": self.code, "name": self.name,
            "points": [list(p) for p in self.points],
            "z_min": self.z_min, "z_max": self.z_max,
            "fill": self.fill, "kind": self.kind,
            "plan": self.plan.to_dict() if self.plan else None,
            "charge_admissible_t_m2": self.charge_admissible_t_m2,
            "obstacles": [list(o) for o in self.obstacles],
            "zones_charge": [dict(z, points=[list(p) for p in z.get("points", [])])
                             for z in self.zones_charge],
            "epontilles": [dict(e) for e in self.epontilles],
        }
        # Les verrous ne s'écrivent que s'il y en a : un dossier qui n'en use
        # pas garde le fichier qu'il avait, au mot près.
        if self.verrouillee:
            d["verrouillee"] = True
        if self.sommets_verrouilles:
            d["sommets_verrouilles"] = [int(i) for i in self.sommets_verrouilles]
        if self.anciens_codes:
            d["anciens_codes"] = [str(c) for c in self.anciens_codes]
        if self.classes_imdg:
            d["classes_imdg"] = [str(c) for c in self.classes_imdg]
        return d

    def changer_code(self, nouveau: str) -> bool:
        """Donne un nouveau code à la cale en gardant l'ancien en mémoire
        (voir `anciens_codes`). Rend True si le code a changé."""
        nouveau = str(nouveau or "").strip().upper()
        if not nouveau or nouveau == self.code:
            return False
        anciens = [c for c in self.anciens_codes if c != nouveau]
        if self.code and self.code != "?" and self.code not in anciens:
            anciens.append(self.code)
        self.anciens_codes = anciens
        self.code = nouveau
        return True

    @classmethod
    def from_dict(cls, d):
        plan = d.get("plan")
        return cls(
            code=d.get("code", "?"), name=d.get("name", ""),
            points=[tuple(p) for p in d.get("points", [])],
            z_min=float(d.get("z_min", 0.0)), z_max=float(d.get("z_max", 0.0)),
            fill=float(d.get("fill", 0.0)), kind=d.get("kind", KIND_CAPACITY),
            pallet=PalletLayout.from_dict(d.get("pallet")),
            plan=Calibrated.from_dict(plan) if plan else None,
            charge_admissible_t_m2=float(d.get("charge_admissible_t_m2", 0.0)),
            obstacles=[list(o) for o in d.get("obstacles", [])],
            zones_charge=[dict(z, points=[tuple(p) for p in z.get("points", [])])
                          for z in d.get("zones_charge", [])],
            # un fichier d'avant les épontilles se relit tel quel : la liste
            # est simplement vide
            epontilles=[dict(e) for e in d.get("epontilles", [])],
            # clé absente = rien de verrouillé : un fichier d'avant les verrous
            # se relit tel quel, et se réécrit tel quel
            verrouillee=bool(d.get("verrouillee", False)),
            sommets_verrouilles=sorted({int(i) for i in
                                        (d.get("sommets_verrouilles") or [])}),
            # clé absente = la cale n'a jamais changé de code
            anciens_codes=[str(c) for c in (d.get("anciens_codes") or [])],
            classes_imdg=[str(c) for c in (d.get("classes_imdg") or [])],
        )


@dataclass
class Deck:
    """Un niveau du navire — une **vue** de l'éditeur de plans : nom, hauteur
    Z, plan calé, capacités. `alias` : le nom du chantier ou du dossier
    (« Tank Top », « Freeboard Deck ») quand il diffère du nom du bord."""

    name: str
    z: float
    plan: Calibrated = field(default_factory=lambda: Calibrated(axes=("X", "Y")))
    capacities: list = field(default_factory=list)
    alias: str = ""
    # CALQUE D'INFORMATION : ce qu'on décalque pour le lire à bord, sans que
    # rien n'en dépende — emplacement des clés de saisissage, d'une descente,
    # d'une prise, une remarque du bord. Ni la stabilité, ni la pose, ni le
    # solveur ne le lisent : il se montre ou s'éteint, c'est tout.
    # [{"type": "trait" | "point" | "texte", "points": [[x, y], ...],
    #   "texte": str, "couleur": "#RRGGBB"}]
    annotations: list = field(default_factory=list)

    @property
    def contour(self):
        return next((c for c in self.capacities if c.kind == KIND_CONTOUR), None)

    def n_capacities(self) -> int:
        return sum(1 for c in self.capacities if c.kind != KIND_CONTOUR)

    def recouvrements(self, tol: float = TOLERANCE_RECOUVREMENT_M):
        """Les paires de cales de CE pont qui se mordent : [(a, b, mètres)].

        Le contour de pont en est exclu : il englobe tout par construction, et
        le signaler reviendrait à crier à chaque cale. Deux cales voisines qui
        se touchent bord à bord non plus — c'est le décalque normal d'une
        cloison —, d'où la tolérance (voir `geometry.profondeur_recouvrement`).

        C'est un AVERTISSEMENT, jamais un refus : le bord doit pouvoir
        enregistrer un plan à moitié retracé et corriger à l'escale suivante.
        """
        caps = [c for c in self.capacities
                if c.kind != KIND_CONTOUR and len(c.points) >= 3]
        out = []
        for i, a in enumerate(caps):
            for b in caps[i + 1:]:
                d = profondeur_recouvrement(a.points, b.points)
                if d > tol:
                    out.append((a, b, d))
        out.sort(key=lambda t: -t[2])
        return out

    def duplicate(self, name: str, z: float) -> "Deck":
        """Copie du plan, du calage et du contour de pont — pas des capacités :
        deux ponts n'ont jamais les mêmes cales, et un code de capacité doit
        rester unique pour retrouver sa table de jauge."""
        d = Deck(name=name, z=z, plan=self.plan.copy(), alias=self.alias)
        c = self.contour
        if c is not None:
            d.capacities.append(Capacity(code=c.code, points=[tuple(p) for p in c.points],
                                         kind=KIND_CONTOUR, z_min=z, z_max=z))
        return d

    def to_dict(self):
        d = {
            "name": self.name, "z": self.z, "alias": self.alias,
            "plan": self.plan.to_dict(),
            "capacities": [c.to_dict() for c in self.capacities],
        }
        if self.annotations:
            d["annotations"] = [dict(a) for a in self.annotations]
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(
            name=d.get("name", "Pont"), z=float(d.get("z", 0.0)),
            plan=Calibrated.from_dict(d.get("plan", {"axes": ["X", "Y"]})),
            capacities=[Capacity.from_dict(c) for c in d.get("capacities", [])],
            alias=d.get("alias", "") or "",
            annotations=[dict(a) for a in (d.get("annotations") or [])
                         if isinstance(a, dict)],
        )


GEOMETRY_FILE = "geometrie.json"
CONDITIONS_DIR = "conditions"


@dataclass
class Project:
    """Géométrie d'un navire : profil, ponts, capacités.

    Depuis la v1.1, elle ne vit plus dans un fichier `.carene.json` à part mais
    dans le **dossier du navire**, à côté des tables (`geometrie.json`) : un
    navire = un dossier, qu'il suffit de copier pour le transporter. Les
    anciens fichiers restent lisibles et sont convertis (`load` +
    `save_geometry`).
    """

    ship_name: str = ""
    profile: Calibrated = field(default_factory=lambda: Calibrated(axes=("X", "Z")))
    decks: list = field(default_factory=list)   # [Deck] triés par z croissant
    path: str = ""                  # ancien fichier .carene.json d'origine
    navire_virtuel_path: str = ""   # dossier du navire (tables + géométrie)

    # ------------------------------------------------------------------ ponts
    def sorted_decks(self):
        return sorted(self.decks, key=lambda d: d.z)

    def deck_above(self, deck: Deck):
        higher = [d for d in self.decks if d.z > deck.z + 1e-6]
        return min(higher, key=lambda d: d.z) if higher else None

    def default_z_range(self, deck: Deck):
        """Étendue verticale par défaut d'une capacité de ce pont."""
        above = self.deck_above(deck)
        return deck.z, (above.z if above else deck.z + 2.0)

    def all_capacities(self):
        for d in self.sorted_decks():
            for c in d.capacities:
                yield d, c

    def recouvrements(self, tol: float = TOLERANCE_RECOUVREMENT_M):
        """Tous les recouvrements de cales du navire : [(pont, a, b, mètres)].

        Sert au rapport d'enregistrement : on enregistre quand même, mais on
        dit ce qui se chevauche, pont par pont."""
        out = []
        for d in self.sorted_decks():
            for a, b, prof in d.recouvrements(tol):
                out.append((d, a, b, prof))
        return out

    def all_epontilles(self):
        """(pont, cale, épontille) pour toutes les épontilles du navire, dans
        l'ordre des ponts puis des cales : c'est la liste que le chargement
        présente à l'officier."""
        for d in self.sorted_decks():
            for c in d.capacities:
                for e in getattr(c, "epontilles", []) or []:
                    yield d, c, e

    def epontilles_fixes(self):
        """Identifiants de toutes les épontilles FIXES du navire. Le chargement
        les compte « en place » d'office et ne les laisse pas déposer."""
        return {e.get("id") for _d, _c, e in self.all_epontilles() if epontille_fixe(e)}

    def epontille(self, eid):
        """(pont, cale, épontille) pour cet identifiant, ou (None, None, None).

        Le chargement ne garde que des identifiants : c'est ici qu'ils
        retrouvent leur emplacement."""
        for d, c, e in self.all_epontilles():
            if e.get("id") == eid:
                return d, c, e
        return None, None, None

    # ------------------------------------------------------------------ vues
    def views(self):
        """Les vues de l'éditeur de plans, dans l'ordre d'affichage : le
        profil d'abord, puis les ponts par Z croissant. Chaque vue :
        (clé, libellé, Deck ou None, Calibrated)."""
        out = [("profil", "Profil longitudinal", None, self.profile)]
        for d in self.sorted_decks():
            out.append(("pont", d.name, d, d.plan))
        return out

    def add_deck(self, name: str, z: float, alias: str = "",
                 copy_plan_from: "Deck | None" = None) -> Deck:
        """Crée une vue de pont ; `copy_plan_from` reprend le plan et le calage
        d'un autre pont (les niveaux d'un même navire sont souvent dessinés
        sur la même feuille)."""
        d = Deck(name=name, z=z, alias=alias)
        if copy_plan_from is not None:
            d.plan = copy_plan_from.plan.copy()
        self.decks.append(d)
        return d

    def duplicate_deck(self, deck: Deck, name: str | None = None,
                       z: float | None = None) -> Deck:
        d = deck.duplicate(name or f"{deck.name} (copie)",
                           deck.z if z is None else z)
        self.decks.append(d)
        return d

    def remove_deck(self, deck: Deck):
        if deck in self.decks:
            self.decks.remove(deck)

    # ------------------------------------------------------------------ JSON
    def _rel(self, p, base):
        if not p:
            return p
        try:
            rel = os.path.relpath(p, base)
            # toujours en « / » dans le fichier : un geometrie.json écrit sous
            # Windows portait « plans\x.png », que les autres systèmes ne
            # relisaient qu'à force de tolérance (D-77)
            return rel.replace(os.sep, "/") if not rel.startswith("..") else p
        except ValueError:
            return p

    def save(self, path: str):
        self.path = path
        base = os.path.dirname(path)
        data = {
            "format": "carene-project",
            "version": 2,
            "ship_name": self.ship_name,
            "profile": self.profile.to_dict(),
            "decks": [d.to_dict() for d in self.sorted_decks()],
            "navire_virtuel_path": self._rel(self.navire_virtuel_path, base),
        }
        self._relativize_paths(data, base)
        with ecriture_atomique(path) as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

    def _relativize_paths(self, data, base):
        """Chemins d'images et de PDF relatifs à `base` dans le dictionnaire
        sérialisé (les objets en mémoire gardent leurs chemins absolus)."""
        self.profile._relativize(data["profile"], base, self._rel)
        for deck, dd in zip(self.sorted_decks(), data["decks"]):
            deck.plan._relativize(dd["plan"], base, self._rel)
            for cap, cc in zip(deck.capacities, dd["capacities"]):
                if cap.plan is not None and cc.get("plan"):
                    cap.plan._relativize(cc["plan"], base, self._rel)

    def _absolutize_paths(self, base):
        self.profile._absolutize(base)
        for d in self.decks:
            d.plan._absolutize(base)
            for c in d.capacities:
                if c.plan is not None:
                    c.plan._absolutize(base)

    @classmethod
    def load(cls, path: str) -> "Project":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("format") != "carene-project":
            raise ValueError("Ce fichier n'est pas un projet Carène.")
        if data.get("version", 1) < 2:
            raise ValueError(
                "Projet v1 (prototype de calage) : recréez le navire avec "
                "l'assistant v2 — le format a évolué (multi-ponts)."
            )
        proj = cls(
            ship_name=data.get("ship_name", ""),
            profile=Calibrated.from_dict(data.get("profile", {})),
            decks=[Deck.from_dict(d) for d in data.get("decks", [])],
            path=path,
            navire_virtuel_path=data.get("navire_virtuel_path", ""),
        )
        base = os.path.dirname(path)
        proj._absolutize_paths(base)
        if proj.navire_virtuel_path and not os.path.isabs(proj.navire_virtuel_path):
            proj.navire_virtuel_path = os.path.normpath(
                os.path.join(base, proj.navire_virtuel_path))
        return proj

    # ------------------------------------------------- dossier du navire
    def _payload(self, base):
        """Dictionnaire sérialisable, chemins d'images relatifs à `base`."""
        data = {
            "format": "carene-geometrie",
            "version": 3,
            "ship_name": self.ship_name,
            "profile": self.profile.to_dict(),
            "decks": [d.to_dict() for d in self.sorted_decks()],
        }
        self._relativize_paths(data, base)
        return data

    def save_geometry(self, folder: str):
        """Écrit la géométrie dans le dossier du navire."""
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, GEOMETRY_FILE)
        with ecriture_atomique(path) as f:
            json.dump(self._payload(folder), f, ensure_ascii=False, indent=1)
        self.navire_virtuel_path = folder
        return path

    @classmethod
    def load_geometry(cls, folder: str) -> "Project":
        """Relit la géométrie depuis le dossier du navire. Renvoie un projet
        vide (mais valide) si le navire n'a pas encore de plans."""
        path = os.path.join(folder, GEOMETRY_FILE)
        if not os.path.exists(path):
            return cls(navire_virtuel_path=folder)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        proj = cls(
            ship_name=data.get("ship_name", ""),
            profile=Calibrated.from_dict(data.get("profile", {})),
            decks=[Deck.from_dict(d) for d in data.get("decks", [])],
            navire_virtuel_path=folder,
        )
        proj._absolutize_paths(folder)
        return proj

    def legacy_pallets(self):
        """Plans de palettes trouvés dans un ancien fichier .carene.json.

        Ils y étaient rangés avec la géométrie ; ils appartiennent désormais à
        une condition de chargement. Renvoie {code: PalletLayout}."""
        return {c.code: c.pallet for _, c in self.all_capacities()
                if c.pallet is not None}
