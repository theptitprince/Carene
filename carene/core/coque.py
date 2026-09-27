# -*- coding: utf-8 -*-
"""Silhouette schématique reconstituée depuis les tables du navire.

Tant qu'aucun plan n'a été calé, il n'y a rien à montrer : la vue de situation
reste vide alors que le dossier contient de quoi dessiner une coque
**cohérente avec la carène**. Ce module la reconstitue.

Il n'utilise **que le dossier du navire** — `navire.json`, la table
hydrostatique et les tables de jaugeage. Aucun document extérieur, aucune
valeur codée en dur : le logiciel installé à bord n'aura que ce dossier.

Ce qui est mesuré, ce qui est déduit
------------------------------------
Pour chaque tirant d'eau tabulé, on construit une ligne d'eau symétrique dont

- l'**aire** vaut exactement l'aire de flottaison du dossier, et
- le **centre** tombe exactement sur le LCF du dossier.

L'aire de flottaison et le LCF sont pris tels quels s'ils figurent dans la
table ; sinon ils sont **dérivés** de la courbe de volume, sans rien inventer :

    WPA = dV/dT        LCF = d(V·LCB)/dT ÷ WPA

Deux paramètres de forme (fullness avant et arrière) suffisent à satisfaire ces
deux contraintes ; ils sont résolus numériquement, ligne d'eau par ligne d'eau.

Restent trois hypothèses, assumées et signalées à l'affichage :

1. la ligne d'eau est prise de la **longueur entre perpendiculaires** — le
   dossier ne dit pas quelle longueur de flottaison correspond à quel tirant
   d'eau ; sa position longitudinale, elle, découle du LCF ;
2. **sous le plus bas tirant d'eau tabulé**, rien n'est mesuré. On y fait
   décroître l'aire en A(T) = A₀·(T/T₀)^q, avec q résolu pour que le volume
   intégré redonne exactement le déplacement tabulé à T₀ — le fond est donc
   contraint par la donnée, même s'il n'est pas décrit par elle ;
3. **au-dessus du plus haut tirant d'eau tabulé**, la muraille est prolongée
   verticalement jusqu'au creux.

La forme rendue n'est donc pas la coque : c'est la seule coque simple qui
respecte, à chaque tirant d'eau tabulé, le volume, l'aire de flottaison et le
centre de flottaison du dossier.
"""
from __future__ import annotations

import copy
import math
import os
from dataclasses import dataclass, field

import numpy as np

RHO_MER = 1.025          # t/m³, densité de référence des tables hydrostatiques


@dataclass
class LigneDeau:
    z_m: float
    points: list = field(default_factory=list)   # [(x, y)] bâbord -> tribord
    aire_m2: float = 0.0
    centre_x_m: float = 0.0
    mesuree: bool = True    # False : reconstituée hors du domaine tabulé


@dataclass
class Coque:
    lignes: list = field(default_factory=list)   # LigneDeau, z croissant
    creux_m: float = 0.0
    longueur_m: float = 0.0
    largeur_m: float = 0.0
    messages: list = field(default_factory=list)

    @property
    def bornes_x(self):
        xs = [p[0] for l in self.lignes for p in l.points]
        return (min(xs), max(xs)) if xs else (0.0, 0.0)

    def contour_au_niveau(self, z_m):
        """Ligne d'eau la plus proche d'une cote, pour poser un pont."""
        if not self.lignes:
            return []
        proche = min(self.lignes, key=lambda l: abs(l.z_m - z_m))
        return list(proche.points)

    def demi_largeur(self, x_m, z_m):
        """Demi-largeur disponible à une abscisse et une cote données."""
        pts = self.contour_au_niveau(z_m)
        ys = [abs(y) for x, y in pts if abs(x - x_m) < 1e-9]
        if ys:
            return max(ys)
        # interpolation le long du contour bâbord
        bab = sorted(((x, abs(y)) for x, y in pts if y >= 0), key=lambda p: p[0])
        if len(bab) < 2:
            return 0.0
        xs = [p[0] for p in bab]
        hs = [p[1] for p in bab]
        return float(np.interp(x_m, xs, hs))


# ------------------------------------------------------------------ profil
def _demi_largeurs(us, k_ar, k_av, u_c):
    """Forme normalisée d'une demi-ligne d'eau, sur tout un tableau
    d'abscisses u dans [0, 1] de l'AR vers l'AV.

    Vaut 1 au maître-couple (u_c) et s'annule aux deux extrémités. `k` grand =
    extrémité pleine (mur), `k` proche de 1 = extrémité effilée. Le calcul est
    vectorisé : la version point par point coûtait à elle seule l'essentiel du
    temps de reconstitution, et plus personne ne l'appelait."""
    us = np.asarray(us, dtype=float)
    ys = np.empty_like(us)
    arriere = us <= u_c
    t = np.zeros_like(us)
    if u_c > 0:
        t[arriere] = (u_c - us[arriere]) / u_c
    ys[arriere] = 1.0 - t[arriere] ** k_ar
    avant = ~arriere
    s = np.zeros_like(us)
    if u_c < 1:
        s[avant] = (us[avant] - u_c) / (1.0 - u_c)
    ys[avant] = 1.0 - s[avant] ** k_av
    return ys


def _aire_et_centre(k_ar, k_av, u_c, n=400):
    """Aire et centre (en fraction de longueur) de la forme normalisée.

    Les deux intégrales se font **à la main** et non plus au trapèze sur 400
    points : la forme est une somme de puissances, dont la primitive est
    connue. C'est exact, et surtout instantané — la dichotomie imbriquée de
    `_resoudre_forme` appelait cette fonction quinze cents fois par ligne
    d'eau, ce qui mettait la reconstitution du navire de
    référence à onze secondes.

        ∫₀^{u_c} 1 − ((u_c−u)/u_c)^k du = u_c · k/(k+1)
        ∫₀^{u_c} u · [1 − ((u_c−u)/u_c)^k] du
                                 = u_c² · [½ − 1/(k+1) + 1/(k+2)]

    et symétriquement pour l'avant. `n` n'est plus utilisé ; il reste au
    prototype pour ne pas casser un appel existant.
    """
    a_ar = u_c * k_ar / (k_ar + 1.0)
    a_av = (1.0 - u_c) * k_av / (k_av + 1.0)
    aire = a_ar + a_av
    if aire <= 0:
        return 0.0, 0.5
    m_ar = u_c * u_c * (0.5 - 1.0 / (k_ar + 1.0) + 1.0 / (k_ar + 2.0))
    m_av = (1.0 - u_c) * (u_c * k_av / (k_av + 1.0)
                          + (1.0 - u_c) * (0.5 - 1.0 / (k_av + 2.0)))
    return aire, (m_ar + m_av) / aire


K_MIN, K_MAX = 1.0, 80.0


def _k_ar_pour_aire(k_av, aire_visee, u_c, tol=1e-9):
    """À `k_av` fixé, l'exposant arrière qui donne l'aire visée.

    L'aire vaut u_c·k_ar/(k_ar+1) + (1−u_c)·k_av/(k_av+1) : elle s'inverse
    directement, là où l'ancienne version faisait quatre-vingts dichotomies.
    Le résultat est borné aux mêmes extrémités qu'avant (`K_MIN`, `K_MAX`),
    donc les cas hors d'atteinte se comportent à l'identique."""
    if u_c <= 0:
        return K_MIN
    reste = aire_visee - (1.0 - u_c) * k_av / (k_av + 1.0)
    r = reste / u_c
    if r >= 1.0:
        return K_MAX
    if r <= 0.5:                      # k_ar/(k_ar+1) ≤ ½ ⇔ k_ar ≤ 1
        return K_MIN
    k = r / (1.0 - r)
    return min(max(k, K_MIN), K_MAX)


def _resoudre_forme(aire_visee, centre_vise, u_c=0.5):
    """(k_ar, k_av) donnant à la fois l'aire et le centre visés.

    Deux inconnues, deux contraintes. `k` grand = extrémité pleine ; remplir
    l'avant recule le centre vers l'avant, remplir l'arrière le recule vers
    l'arrière. On imbrique deux dichotomies : l'intérieure tient l'aire,
    l'extérieure déplace le centre. Chacune est monotone, donc sûre.
    """
    aire_visee = min(max(aire_visee, 0.34), 0.995)
    centre_vise = min(max(centre_vise, 0.25), 0.75)

    def centre_pour(k_av):
        k_ar = _k_ar_pour_aire(k_av, aire_visee, u_c)
        return _aire_et_centre(k_ar, k_av, u_c)[1], k_ar

    a, b = K_MIN, K_MAX
    ca, k_a = centre_pour(a)
    cb, k_b = centre_pour(b)
    if centre_vise <= min(ca, cb):
        return (k_a, a) if ca <= cb else (k_b, b)
    if centre_vise >= max(ca, cb):
        return (k_a, a) if ca >= cb else (k_b, b)
    croissant = cb > ca
    k_ar = k_a
    for _ in range(80):
        m = 0.5 * (a + b)
        c, k_ar = centre_pour(m)
        if (c < centre_vise) == croissant:
            a = m
        else:
            b = m
        if b - a < 1e-9:
            break
    k_av = 0.5 * (a + b)
    k_ar = _k_ar_pour_aire(k_av, aire_visee, u_c)
    return k_ar, k_av


def _colonne(rows, nom):
    return np.array([float(r[nom]) for r in rows]) if rows and nom in rows[0] \
        else None


def _derive(x, y):
    """dy/dx aux points tabulés (différences centrées, décentrées aux bords)."""
    return np.gradient(np.asarray(y, dtype=float), np.asarray(x, dtype=float))


# ------------------------------------------------------------------ coque
def reconstituer(navire, n_points=61, assiette_m=0.0):
    """Construit la silhouette schématique. Retourne une `Coque`.

    `n_points` est le nombre de points par demi-ligne d'eau. Il était accepté
    sans être transmis : demander une coque plus légère n'avait aucun effet.
    Son défaut est celui de `_ligne` (61), pour que le dessin reste le même
    qu'avant — il se baisse pour une vignette, se monte pour un tracé coté."""
    c = Coque()
    dims = navire.manifest.get("dimensions", {})
    L = float(dims.get("longueur_entre_pp_hydro_m") or 0.0)
    B = float(dims.get("largeur_hors_membres_m") or 0.0)
    D = float(dims.get("creux_sur_quille_m") or 0.0)
    if L <= 0 or B <= 0:
        c.messages.append("Longueur entre perpendiculaires ou largeur "
                          "manquante : silhouette impossible.")
        return c
    c.longueur_m, c.largeur_m, c.creux_m = L, B, D or 0.0

    rows = _lignes_hydro(navire, assiette_m)
    if len(rows) < 2:
        c.messages.append("Table hydrostatique trop courte pour reconstituer "
                          "une carène.")
        return c

    T = _colonne(rows, "TE_milieu_m")
    V = _colonne(rows, "Volume_m3")
    if V is None:
        depl = _colonne(rows, "Deplacement_t")
        if depl is None:
            c.messages.append("Ni volume ni déplacement tabulés.")
            return c
        V = depl / RHO_MER
        c.messages.append("Volume déduit du déplacement (densité "
                          f"{RHO_MER:g}), la table ne le donne pas.")

    wpa = _colonne(rows, "WPA_m2")
    if wpa is None or np.any(wpa <= 0):
        wpa = _derive(T, V)
        c.messages.append("Aire de flottaison déduite de la pente du volume "
                          "(WPA = dV/dT), la table ne la donne pas.")
    lcb = _colonne(rows, "LCB_m")
    lcf = _colonne(rows, "LCF_m")
    if lcf is None or np.any(~np.isfinite(lcf)):
        if lcb is None:
            c.messages.append("Ni LCF ni LCB tabulés : centre de flottaison "
                              "supposé au milieu.")
            lcf = np.full_like(T, np.nan)
        else:
            lcf = _derive(T, V * lcb) / np.where(wpa > 0, wpa, np.nan)
            c.messages.append("Centre de flottaison déduit de la pente du "
                              "moment de carène, la table ne le donne pas.")

    # --- position longitudinale de la coque, fixée une fois pour toutes
    # Les lignes d'eau d'un navire se terminent toutes à peu près à l'étrave et
    # à l'étambot : c'est la FORME qui change avec le tirant d'eau, pas la
    # position des extrémités. On cale donc l'étendue sur la ligne d'eau la
    # plus profonde (la plus pleine, donc la mieux définie), puis toutes les
    # autres jouent sur leur forme pour retrouver leur propre LCF.
    lcf_ref = float(lcf[-1]) if np.isfinite(lcf[-1]) else \
        (float(lcb[-1]) if lcb is not None else 0.0)
    x_ar = lcf_ref - 0.5 * L

    # --- lignes d'eau tabulées
    for i in range(len(T)):
        aire = float(wpa[i])
        if aire <= 0:
            continue
        xc = float(lcf[i]) if np.isfinite(lcf[i]) else None
        c.lignes.append(_ligne(T[i], aire, xc, L, B, x_ar, mesuree=True,
                               n_points=n_points))

    # --- fond : sous le plus bas tirant d'eau, rien n'est tabulé. On fait
    # décroître l'aire en (T/T0)^q avec q tel que le volume intégré redonne
    # exactement le déplacement tabulé à T0.
    t0, a0, v0 = float(T[0]), float(wpa[0]), float(V[0])
    if v0 > 0 and a0 * t0 > v0:
        q = a0 * t0 / v0 - 1.0
        xc = float(lcf[0]) if np.isfinite(lcf[0]) else None
        # échantillonnage resserré près de la quille : avec un exposant faible
        # (fond plat), l'aire monte très vite sur les premiers centimètres
        for frac in (0.02, 0.05, 0.10, 0.18, 0.30, 0.45, 0.62, 0.80):
            z = t0 * frac
            aire = a0 * (z / t0) ** q
            c.lignes.append(_ligne(z, aire, xc, L, B, x_ar, mesuree=False,
                                   n_points=n_points))
        c.messages.append(
            f"Fond reconstitué sous {t0:.2f} m : aire en (T/T₀)^{q:.2f}, "
            "exposant résolu pour retrouver le déplacement tabulé. Le dossier "
            "ne décrit pas cette partie.")
    # --- pont : muraille prolongée verticalement jusqu'au creux
    if D > float(T[-1]):
        haute = c.lignes[-1] if c.lignes else None
        if haute is not None:
            c.lignes.append(LigneDeau(z_m=D, points=list(haute.points),
                                      aire_m2=haute.aire_m2,
                                      centre_x_m=haute.centre_x_m,
                                      mesuree=False))
            c.messages.append(
                f"Au-dessus de {float(T[-1]):.2f} m, la muraille est prolongée "
                f"verticalement jusqu'au creux ({D:.2f} m) : le dossier "
                "hydrostatique s'arrête là.")
    c.lignes.sort(key=lambda l: l.z_m)
    return c


# ----------------------------------------------------- mémoire du navire
# `reconstituer` reste pure : c'est elle que les tests interrogent, et deux
# appels de suite doivent donner deux fois le même calcul. Mais les VUES, elles,
# reconstituent toutes la même coque — la vue Capacités, chaque `ProfilView`
# (une par rapport exporté), la coupe — pour un navire qui, lui, ne change pas
# de la session. On la garde donc ici, au niveau du module, pour que tout le
# monde partage la même.
#
# La clé porte le **dossier du navire** et l'identité de ses tables : un navire
# rechargé (nouvel objet, ou dossier changé) recalcule. Rien de ce qui dépend du
# CHARGEMENT n'est gardé : le remplissage, les poids, les résultats sont
# recalculés à chaque fois. Ne sont mis en cache que les données propres au
# navire — la coque et l'emprise des capacités.
_MEMO = []              # [(clé, navire, Coque, [BoiteCapacite])], récent en tête
_MEMO_MAX = 3


def _dossier_courant():
    try:
        from .. import app_paths
        return app_paths.ship_folder() or ""
    except Exception:                              # pragma: no cover
        return ""


def _cle_navire(navire):
    """Ce qui distingue un navire d'un autre, du point de vue de sa coque.

    `id(navire)` suffirait presque, mais un objet libéré peut voir son
    identifiant réattribué : l'entrée garde donc une référence forte sur le
    navire, et la clé y ajoute le dossier et la signature des tables — ce qui
    fait aussi recalculer quand on retire une colonne à la table (les tests le
    font) ou quand on change une dimension principale."""
    h = getattr(navire, "hydro", None)
    dims = (getattr(navire, "manifest", None) or {}).get("dimensions", {}) or {}
    colonnes = getattr(h, "columns", None)
    axe = getattr(h, "axis1", None)
    # le dossier vient du navire lui-même quand il le porte : `ship_folder()`
    # relit le fichier de configuration à chaque appel, et cette clé est
    # calculée à chaque repeint de la vue de profil
    dossier = getattr(navire, "path", None) or _dossier_courant()
    return (dossier, id(navire), id(h),
            tuple(colonnes) if colonnes is not None else (),
            len(axe) if axe is not None else 0,
            tuple(sorted((str(k), repr(v)) for k, v in dims.items())),
            tuple(sorted(getattr(navire, "capacities", None) or {})))


def _entree(navire):
    cle = _cle_navire(navire)
    for i, e in enumerate(_MEMO):
        if e[0] == cle:
            if i:
                _MEMO.insert(0, _MEMO.pop(i))
            return _MEMO[0]
    c = reconstituer(navire)
    boites = boites_capacites(navire, c if c.lignes else None)
    _MEMO.insert(0, (cle, navire, c, boites))
    del _MEMO[_MEMO_MAX:]
    return _MEMO[0]


def coque_du_navire(navire):
    """La silhouette schématique du navire, reconstituée **une seule fois**.

    À utiliser partout dans l'interface et les rapports ; `reconstituer` reste
    disponible pour qui veut le calcul brut."""
    if navire is None:
        return None
    c = _entree(navire)[2]
    return c if c.lignes else None


def boites_du_navire(navire):
    """Les boîtes de capacités du navire, calculées une seule fois.

    Elles sont rendues en **copie** : la vue de situation y écrit le taux de
    remplissage relevé (`fill`), qui dépend du chargement et n'a rien à faire
    dans un cache partagé."""
    if navire is None:
        return []
    return [copy.copy(b) for b in _entree(navire)[3]]


def invalider(navire=None):
    """Oublie ce qui est gardé en mémoire (changement de navire, tests)."""
    if navire is None:
        _MEMO.clear()
        return
    cle = _cle_navire(navire)
    _MEMO[:] = [e for e in _MEMO if e[0] != cle]


# ----------------------------------------------------- plan des formes tracé
_MEMO_FORMES = {}


def formes_du_navire(dossier=None):
    """Le plan des formes décalqué (`formes.json`), ou None.

    Branché **défensivement** : le module `formes` peut ne pas exister encore,
    le fichier peut être absent ou illisible — dans tous ces cas on retombe sur
    la reconstitution schématique, qui reste le comportement de référence.

    D-10 s'applique tel quel : une forme décalquée sert à la VUE, jamais au
    calcul. Elle change seulement le nom de ce qu'on montre — « silhouette
    schématique » devient le nom du plan relevé."""
    dossier = dossier or _dossier_courant()
    if not dossier:
        return None
    try:
        chemin = os.path.join(dossier, "formes.json")
        signature = os.path.getmtime(chemin) if os.path.exists(chemin) else None
    except OSError:                                # pragma: no cover
        signature = None
    cle = (dossier, signature)
    if cle in _MEMO_FORMES:
        return _MEMO_FORMES[cle]
    f = None
    if signature is not None:
        try:
            from . import formes as _formes
            f = _formes.charger(dossier)
        except Exception:                          # pragma: no cover
            f = None
    _MEMO_FORMES.clear()
    _MEMO_FORMES[cle] = f
    return f


def _ligne(z, aire, xc, L, B, x_ar, mesuree, n_points=61):
    """Une ligne d'eau d'aire et de centre imposés, sur l'étendue [x_ar, +L]."""
    u_c = 0.5
    cw = aire / (L * B)                       # coefficient de flottaison visé
    u_vise = 0.5 if xc is None else (xc - x_ar) / L
    k_ar, k_av = _resoudre_forme(cw, u_vise, u_c)

    a_norm, u_obtenu = _aire_et_centre(k_ar, k_av, u_c)
    us = np.linspace(0.0, 1.0, n_points)
    demi = _demi_largeurs(us, k_ar, k_av, u_c)
    # échelle de largeur : l'aire doit valoir EXACTEMENT celle du dossier
    ech = (cw / a_norm) if a_norm > 0 else 1.0
    demi = demi * (B / 2.0) * ech
    xs = x_ar + us * L

    bab = [(float(x), float(h)) for x, h in zip(xs, demi)]
    tri = [(x, -h) for x, h in reversed(bab)]
    return LigneDeau(z_m=float(z), points=bab + tri, aire_m2=float(aire),
                     centre_x_m=float(x_ar + u_obtenu * L), mesuree=mesuree)


def _lignes_hydro(navire, assiette_m):
    """Lignes de la table hydrostatique à l'assiette demandée (la plus proche
    tabulée), triées par tirant d'eau."""
    grille = navire.hydro
    a1 = list(grille.axis1)
    if not a1:
        return []
    i = min(range(len(a1)), key=lambda k: abs(a1[k] - assiette_m))
    axis2 = grille.rows_axis2[i]
    vals = grille.rows_values[i]
    rows = []
    for j in range(len(axis2)):
        r = {col: float(vals[col][j]) for col in vals}
        r.setdefault("TE_milieu_m", float(axis2[j]))
        rows.append(r)
    rows.sort(key=lambda r: r["TE_milieu_m"])
    return rows


# ------------------------------------------------------------ capacités
@dataclass
class BoiteCapacite:
    nom: str
    x0: float
    y0: float
    x1: float
    y1: float
    z_min: float
    z_max: float
    volume_m3: float = 0.0
    type: str = ""
    approx: str = ""        # ce qui a été supposé faute de donnée
    fill: float = 0.0       # taux de remplissage 0..1, pour la visualisation


def reprendre_en_geometrie(navire, project, coque=None, boites=None):
    """Écrit la silhouette schématique dans la géométrie du navire.

    Elle cesse alors d'être schématique : elle devient le tracé de
    l'utilisateur, à retoucher dans l'éditeur de plans. On ne touche à rien de
    ce qui est déjà tracé — ni contour de pont existant, ni capacité déjà
    dessinée. Retourne (nb_ponts, nb_capacites) ajoutés.
    """
    from ..project import KIND_CAPACITY, KIND_CONTOUR, Capacity, Deck

    c = coque if coque is not None else reconstituer(navire)
    if not c.lignes:
        return 0, 0
    b = boites if boites is not None else boites_capacites(navire, c)

    if not project.decks:
        for i, z in enumerate(ponts_suggeres(c, navire)):
            project.decks.append(Deck(name=f"Pont {i + 1}", z=float(z)))
    deja = {cap.code for _, cap in project.all_capacities()}
    n_ponts = n_caps = 0

    for deck in project.sorted_decks():
        contour = next((x for x in deck.capacities
                        if x.kind == KIND_CONTOUR and len(x.points) >= 3), None)
        if contour is None:
            pts = c.contour_au_niveau(deck.z)
            if len(pts) >= 3:
                deck.capacities.append(Capacity(
                    code=f"CONTOUR {deck.name}", name=f"Contour {deck.name}",
                    points=[(float(x), float(y)) for x, y in pts],
                    z_min=float(deck.z), z_max=float(deck.z),
                    kind=KIND_CONTOUR))
                n_ponts += 1

    if project.decks:
        for boite in b:
            if boite.nom in deja:
                continue
            # la capacité est rattachée au pont dont la cote encadre son fond
            deck = min(project.sorted_decks(),
                       key=lambda d: abs(d.z - boite.z_min))
            deck.capacities.append(Capacity(
                code=boite.nom, name=boite.type,
                points=[(boite.x0, boite.y0), (boite.x1, boite.y0),
                        (boite.x1, boite.y1), (boite.x0, boite.y1)],
                z_min=float(boite.z_min), z_max=float(boite.z_max),
                kind=KIND_CAPACITY))
            n_caps += 1
    return n_ponts, n_caps


def ponts_suggeres(coque, navire, n=2):
    """Cotes de pont plausibles quand aucun pont n'a été défini.

    On les place au-dessus de la dernière capacité, régulièrement jusqu'au
    creux : c'est une commodité d'affichage, pas une donnée du dossier."""
    if coque.creux_m <= 0:
        return []
    hauts = [b.z_max for b in boites_capacites(navire, coque)]
    bas = max(hauts) if hauts else coque.creux_m / 3.0
    if bas >= coque.creux_m:
        return [coque.creux_m]
    pas = (coque.creux_m - bas) / max(1, n)
    return [round(bas + pas * (i + 1), 3) for i in range(n)]


def boites_capacites(navire, coque=None, rapport_l_sur_w=2.5):
    """Une boîte par capacité, déduite de sa table de jaugeage.

    - **hauteur** : sondage à 100 % — c'est la profondeur de la capacité ;
    - **fond** : ajusté sur la table, VCG(sonde) valant z_fond + sonde/2 pour
      une capacité prismatique ; on prend la moyenne des écarts, ce qui
      absorbe les capacités qui ne le sont pas tout à fait ;
    - **aire au sol** : volume net ÷ hauteur ;
    - **centre** : LCG et TCG à 100 %.

    Reste supposé : le **partage de cette aire entre longueur et largeur**. On
    prend un rectangle allongé dans l'axe du navire (rapport par défaut 2,5),
    rogné pour tenir dans la coque à sa cote. C'est la seule hypothèse de ce
    module qui ne soit pas contrainte par le dossier — elle est reportée dans
    `approx`.
    """
    out = []
    for nom, cap in (getattr(navire, "capacities", None) or {}).items():
        rows = cap.jauge_rows
        if not rows:
            continue
        plein = cap.at_fill_pc(100.0)
        vol = float(plein.get("Volume_m3", 0.0) or 0.0)
        if vol <= 0:
            continue
        approx = []

        h = float(plein.get("Sondage_m", 0.0) or 0.0)
        z_fond = None
        if h > 0:
            ecarts = []
            for r in rows:
                s = float(r.get("Sondage_m", 0.0) or 0.0)
                v = float(r.get("VCG_m", 0.0) or 0.0)
                if s > 1e-6 and v > 0:
                    ecarts.append(v - s / 2.0)
            if ecarts:
                z_fond = float(np.mean(ecarts))
        if h <= 0 or z_fond is None:
            # pas de sondage tabulé : cube de même volume centré sur le VCG
            h = vol ** (1.0 / 3.0)
            z_fond = float(plein.get("VCG_m", h / 2.0) or h / 2.0) - h / 2.0
            approx.append("hauteur supposée (aucun sondage tabulé)")
        z_fond = max(0.0, z_fond)

        aire = vol / h
        largeur = math.sqrt(aire / rapport_l_sur_w)
        longueur = aire / largeur
        approx.append(f"emprise supposée {longueur:.1f} × {largeur:.1f} m "
                      f"(aire {aire:.1f} m² du dossier, partage supposé)")

        xc = float(plein.get("LCG_m", 0.0) or 0.0)
        yc = float(plein.get("TCG_m", 0.0) or 0.0)
        if coque is not None:
            dispo = coque.demi_largeur(xc, z_fond + h / 2.0)
            if dispo > 0:
                # la boîte ne doit pas déborder de la muraille
                marge = dispo - abs(yc)
                if marge > 0.05:
                    largeur = min(largeur, 2.0 * marge)
                    longueur = aire / max(largeur, 1e-6)
        out.append(BoiteCapacite(
            nom=nom, x0=xc - longueur / 2, y0=yc - largeur / 2,
            x1=xc + longueur / 2, y1=yc + largeur / 2,
            z_min=z_fond, z_max=z_fond + h, volume_m3=vol,
            type=str(cap.meta.get("Type", "") or ""),
            approx=" · ".join(approx)))
    return out
