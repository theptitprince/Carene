# -*- coding: utf-8 -*-
"""Courbe de redressement (GZ), corrections de carène liquide, aires sous la
courbe, angle d'envahissement — aucune donnée navire codée en dur : tout vient
de l'objet Navire (tables KN, points d'envahissement, repères de tirants d'eau
depuis navire.json) et de la condition de chargement passée en paramètre.
"""
import math
from dataclasses import dataclass, field

import numpy as np

from .interp import pchip_eval


@dataclass
class GZResult:
    heel_deg: list
    gz_m: list
    kg_effectif_m: float
    gm_solide_m: float
    gm_corrige_m: float
    # GZmax, angle du GZmax et angle d'annulation sont mesurés **depuis la
    # gîte d'équilibre**, dans le sens où le navire est déjà couché : c'est la
    # stabilité résiduelle, la seule qui ait un sens quand il y a une bande.
    # Sur un navire droit (origine_deg = 0) ces valeurs sont inchangées.
    gz_max_m: float = 0.0
    angle_gz_max_deg: float = 0.0
    angle_annulation_deg: float = None
    angle_gz_max_absolu_deg: float = 0.0
    # courbe vue depuis l'équilibre : x >= 0, GZ résiduel
    origine_deg: float = 0.0            # gîte d'équilibre, None si aucune
    sens: int = 1                       # +1 / -1 : côté vers lequel il gîte
    heel_residuel_deg: list = field(default_factory=list)
    gz_residuel_m: list = field(default_factory=list)
    # domaines : la table KN n'a pas les mêmes bornes que l'hydrostatique
    dans_domaine_kn: bool = True
    residuel_max_deg: float = 0.0     # dernier angle résiduel réellement tabulé
    extra: dict = field(default_factory=dict)


def _zero_stable(pts):
    """Zéro **stable** de GZ le plus proche de la verticale, ou None.

    Un zéro à pente descendante est un équilibre instable : le navire ne s'y
    pose pas, il en repart. Seule une traversée ascendante est retenue.
    `pts` est une suite (angle, GZ) triée par angle croissant.
    """
    meilleur = None
    for (a0, g0), (a1, g1) in zip(pts, pts[1:]):
        if g0 == 0.0 and g1 > g0:
            candidat = a0
        elif g0 * g1 < 0 and g1 > g0:
            candidat = a0 + (a1 - a0) * (-g0) / (g1 - g0)
        else:
            continue
        if meilleur is None or abs(candidat) < abs(meilleur):
            meilleur = candidat
    return meilleur


def angle_equilibre_deg(gz_res):
    """Gîte d'équilibre lue sur une courbe GZ déjà calculée.

    Retourne **None** si aucun zéro stable ne tombe dans l'étendue de la
    courbe : avec un TCG marqué, l'équilibre peut se situer bien au-delà des
    bornes usuelles (-10°…+60°), et renvoyer 0° dans ce cas afficherait un
    navire droit alors qu'il est couché. Pour une valeur sûre quelle que soit
    la gîte, utiliser `angle_equilibre`, qui balaie tout le domaine des
    pantocarènes.
    """
    return _zero_stable(sorted(zip(gz_res.heel_deg, gz_res.gz_m)))


def angle_equilibre(navire, equilibre, vcg_m, tcg_m=0.0, fsm_total_tm=0.0,
                    kn_method="pchip", pas_deg=0.5):
    """Gîte à laquelle le navire flotte réellement, cherchée sur tout le
    domaine des pantocarènes (± l'angle maximal tabulé), et non sur l'étendue
    de tracé de la courbe GZ.

    Retourne l'angle en degrés, ou **None** s'il n'existe aucun équilibre
    stable dans le domaine tabulé — cas d'un navire que rien ne redresse, à
    présenter comme non exploitable et surtout pas arrondi à zéro.
    """
    kge = kg_effectif(vcg_m, equilibre.displacement_t, fsm_total_tm)
    hmax = max(navire.kn_heel_angles) if navire.kn_heel_angles else 60.0
    heels = list(np.arange(-hmax, hmax + pas_deg / 2, pas_deg))
    pts = [(h, _gz_point(navire, equilibre, kge, tcg_m, h, kn_method))
           for h in heels]
    a = _zero_stable(pts)
    return None if a is None else float(a)


def kg_effectif(vcg_m, displacement_t, fsm_total_tm):
    """Rehaussement virtuel de G par carène liquide : KGeff = VCG + ΣFSM/Δ."""
    if displacement_t <= 0:
        return vcg_m
    return vcg_m + fsm_total_tm / displacement_t


def _gz_point(navire, equilibre, kg_eff_m, tcg_m, heel_deg, kn_method="pchip"):
    """Bras de redressement à une gîte donnée, gîte permanente comprise.

    GZ = KN − KGeff·sin(φ) − TCG·cos(φ). La table KN n'étant donnée qu'à
    droite, `navire.kn_at` la prolonge par symétrie de coque pour φ < 0.
    """
    kn = navire.kn_at(equilibre.trim_m, equilibre.displacement_t, heel_deg,
                      method=kn_method)
    return (kn - kg_eff_m * math.sin(math.radians(heel_deg))
            - tcg_m * math.cos(math.radians(heel_deg)))


def gz_curve(navire, equilibre, vcg_m, tcg_m=0.0, fsm_total_tm=0.0,
             heel_min=-10.0, heel_max=60.0, step_deg=1.0, kn_method="pchip"):
    """Calcule la courbe GZ(heel) sur [heel_min, heel_max] à partir des
    pantocarènes KN(assiette, déplacement, gîte) du navire virtuel, avec
    correction de carène liquide (rehaussement de KG) et bras de gîte
    permanente si TCG != 0.

    Domaine fiable : celui de la table KN du navire (voir navire.kn_heel_angles,
    typiquement 0-60° pour le navire de référence) ; au-delà, KN est extrapolé linéairement et
    la courbe perd en précision.
    """
    kge = kg_effectif(vcg_m, equilibre.displacement_t, fsm_total_tm)
    heels = list(np.arange(heel_min, heel_max + step_deg / 2, step_deg))
    gzs = [_gz_point(navire, equilibre, kge, tcg_m, h, kn_method) for h in heels]

    gm_solide = navire.hydro.value(equilibre.trim_m, equilibre.draft_m, "KMt_m") - vcg_m
    gm_corrige = gm_solide - (fsm_total_tm / equilibre.displacement_t if equilibre.displacement_t else 0.0)

    res = GZResult(heel_deg=heels, gz_m=gzs, kg_effectif_m=kge,
                    gm_solide_m=gm_solide, gm_corrige_m=gm_corrige,
                    dans_domaine_kn=navire.domaine_kn(
                        equilibre.trim_m, equilibre.displacement_t),
                    # on garde les entrées : sans le TCG, impossible de
                    # retrouver la gîte d'équilibre à partir du seul résultat
                    extra={"vcg_m": vcg_m, "tcg_m": tcg_m,
                           "fsm_total_tm": fsm_total_tm,
                           "heel_min": heel_min, "heel_max": heel_max,
                           "kn_method": kn_method})
    _courbe_residuelle(res, navire, equilibre, kge, tcg_m, heel_max, step_deg,
                       kn_method)
    _annotate_peak_and_vanishing(res)
    return res


def _courbe_residuelle(res, navire, equilibre, kge, tcg_m, x_max, step_deg,
                       kn_method):
    """Construit la courbe vue depuis la gîte d'équilibre.

    Avec une bande permanente, la stabilité qui compte est celle qu'il reste
    **à partir de la position où le navire flotte**, et du côté où il est déjà
    couché : c'est de là que se mesurent les aires réglementaires et le GZmax.
    Sur un navire droit, l'origine vaut 0° et la courbe résiduelle est la
    courbe elle-même — les résultats sont alors rigoureusement inchangés.

    Elle est recalculée sur les pantocarènes, et non rééchantillonnée sur la
    courbe tracée : avec 12° de bande, il faudrait sinon lire la courbe jusqu'à
    52° au-delà de son étendue, donc l'extrapoler.
    """
    phi_e = angle_equilibre(navire, equilibre, res.extra["vcg_m"], tcg_m,
                            res.extra["fsm_total_tm"], kn_method=kn_method)
    res.origine_deg = phi_e
    if phi_e is None:
        # aucun équilibre stable : il n'y a pas de stabilité résiduelle à
        # mesurer, et surtout pas depuis 0° comme si le navire était droit
        res.heel_residuel_deg, res.gz_residuel_m = [], []
        res.residuel_max_deg = 0.0
        return
    res.sens = 1 if phi_e >= 0 else -1
    # On ne prolonge pas les pantocarènes : la courbe résiduelle s'arrête au
    # dernier angle tabulé. Avec une forte bande, elle est donc plus courte, et
    # peut ne plus atteindre les 40° qu'exigent les critères — c'est un fait à
    # dire, pas à combler par extrapolation.
    hmax = max(navire.kn_heel_angles) if navire.kn_heel_angles else x_max
    x_fin = min(x_max, max(0.0, hmax - abs(phi_e)))
    xs = list(np.arange(0.0, x_fin + step_deg / 2, step_deg))
    if len(xs) < 2:
        res.heel_residuel_deg, res.gz_residuel_m = [], []
        res.residuel_max_deg = x_fin
        return
    res.heel_residuel_deg = xs
    res.gz_residuel_m = [
        res.sens * _gz_point(navire, equilibre, kge, tcg_m,
                             phi_e + res.sens * x, kn_method) for x in xs]
    res.residuel_max_deg = xs[-1]


def _annotate_peak_and_vanishing(res):
    """GZmax et angle d'annulation, mesurés sur la courbe résiduelle."""
    heels, gzs = res.heel_residuel_deg, res.gz_residuel_m
    if not heels:
        res.gz_max_m, res.angle_gz_max_deg = 0.0, 0.0
        res.angle_gz_max_absolu_deg, res.angle_annulation_deg = 0.0, None
        return
    i_max = max(range(len(heels)), key=lambda i: gzs[i])
    res.angle_gz_max_deg, res.gz_max_m = heels[i_max], gzs[i_max]
    # LE SOMMET, PAS LE POINT DE GRILLE (R-8, D-78) : la courbe est calculée
    # au degré, et le critère des 25° se décidait donc à ±0,5° près. On pose
    # une parabole sur le point le plus haut et ses deux voisins : c'est le
    # sommet de la courbe, retrouvé à quelques centièmes de degré (recueil
    # de référence, cas 01 : 49,18°, là où la grille disait 49°).
    if 0 < i_max < len(heels) - 1:
        x0, x1, x2 = heels[i_max - 1], heels[i_max], heels[i_max + 1]
        y0, y1, y2 = gzs[i_max - 1], gzs[i_max], gzs[i_max + 1]
        denom = (y0 - 2.0 * y1 + y2)
        if denom < 0 and abs(x2 - x1 - (x1 - x0)) < 1e-9:
            h = x1 - x0
            dx = 0.5 * h * (y0 - y2) / denom
            if abs(dx) <= h:
                res.angle_gz_max_deg = x1 + dx
                res.gz_max_m = y1 - 0.25 * (y0 - y2) * dx / h
    res.angle_gz_max_absolu_deg = (res.origine_deg or 0.0) \
        + res.sens * res.angle_gz_max_deg
    res.angle_annulation_deg = None
    for i in range(i_max, len(heels) - 1):
        g0, g1 = gzs[i], gzs[i + 1]
        if g0 >= 0 and g1 < 0:
            h0, h1 = heels[i], heels[i + 1]
            res.angle_annulation_deg = h0 + (h1 - h0) * (g0 / (g0 - g1))
            break


def gz_at(res, heel_deg):
    """GZ sur la courbe **physique**, à une gîte comptée depuis la verticale."""
    return float(pchip_eval(res.heel_deg, res.gz_m, heel_deg))


def gz_residuel_at(res, x_deg):
    """GZ résiduel, à un angle compté depuis la gîte d'équilibre."""
    if not res.heel_residuel_deg:
        return float("nan")
    return float(pchip_eval(res.heel_residuel_deg, res.gz_residuel_m, x_deg))


def _simpson(xs_deg, ys):
    h = math.radians(xs_deg[1] - xs_deg[0])
    aire = ys[0] + ys[-1] + 4 * sum(ys[1:-1:2]) + 2 * sum(ys[2:-1:2])
    return float(aire * h / 3)


def area_under_gz(res, heel_from_deg, heel_to_deg, n=240):
    """Aire sous la courbe **physique** entre deux gîtes (m.rad), méthode de
    Simpson sur une évaluation PCHIP fine. n doit être pair."""
    if n % 2:
        n += 1
    xs = np.linspace(heel_from_deg, heel_to_deg, n + 1)
    return _simpson(xs, pchip_eval(res.heel_deg, res.gz_m, xs))


def aire_residuelle(res, x_from_deg, x_to_deg, n=240):
    """Aire sous la courbe **résiduelle**, entre deux angles comptés depuis la
    gîte d'équilibre. C'est l'aire des critères IS2008."""
    if not res.heel_residuel_deg or x_to_deg <= x_from_deg:
        return float("nan")
    if x_to_deg > res.heel_residuel_deg[-1] + 1e-9:
        return float("nan")     # prolonger la table serait inventer une aire
    if n % 2:
        n += 1
    xs = np.linspace(x_from_deg, x_to_deg, n + 1)
    return _simpson(xs, pchip_eval(res.heel_residuel_deg, res.gz_residuel_m, xs))


def abscisses_tirants_eau(navire):
    """(x_arrière, x_avant, source) des deux stations où sont donnés HAP et HFP.

    HAP et HFP, comme les colonnes TE_AR_m / TE_AV_m de la table
    hydrostatique, sont les tirants d'eau **aux perpendiculaires** : sur
    le navire de référence, TE_AR − TE_AV vaut exactement l'assiette tabulée, sur la longueur
    entre perpendiculaires (64,726 m). Les *repères* de tirants d'eau peints
    sur la coque sont ailleurs (1,75 m et 61,20 m du couple 0, soit 59,45 m
    d'écart) : les confondre surestime la pente d'assiette de près de 9 %.

    On lit donc `dimensions.perpendiculaires` si le dossier la renseigne
    (`{"arriere_m": ..., "avant_m": ...}`). Faute de quoi on retombe sur les
    repères, en le disant : la troisième valeur rendue vaut alors
    "reperes" et l'appelant doit présenter le résultat comme approché.
    """
    dims = navire.manifest.get("dimensions", {})
    pp = dims.get("perpendiculaires")
    if isinstance(pp, dict) and "arriere_m" in pp and "avant_m" in pp:
        return float(pp["arriere_m"]), float(pp["avant_m"]), "perpendiculaires"
    reperes = dims.get("reperes_tirants_eau", {})
    try:
        x_ar = float(reperes["arriere"].split("(")[1].split("m")[0].strip())
        x_av = float(reperes["avant"].split("(")[1].split("m")[0].strip())
    except (KeyError, IndexError, ValueError):
        return 0.0, 0.0, "inconnu"
    return x_ar, x_av, "reperes"


def source_tirants_eau(navire):
    """Sur quoi repose la pente de flottaison : "perpendiculaires" (le dossier
    les donne), "reperes" (repli sur les repères peints, approché) ou
    "inconnu" (ni l'un ni l'autre — flottaison prise horizontale).

    `local_draft` rend un nombre et `downflooding_angle` un couple
    (angle, repère) : aucun des deux ne peut porter ce drapeau sans changer sa
    signature, et tous deux sont appelés depuis plusieurs vues et plusieurs
    outils. La source se demande donc à part — elle ne dépend que du navire,
    jamais du point de calcul. C'est `criteria.evaluate_general` qui la lit
    pour prévenir que θf est approché.
    """
    return abscisses_tirants_eau(navire)[2]


def local_draft(navire, x_m, hap_m, hfp_m):
    """Tirant d'eau local, par interpolation linéaire de la flottaison entre
    les deux stations où HAP et HFP sont définis (voir
    `abscisses_tirants_eau` : perpendiculaires si le dossier les donne,
    repères de tirants d'eau sinon — approximation alors signalée par
    `source_tirants_eau`, que cette fonction ne peut pas rendre elle-même)."""
    x_ar, x_av, _source = abscisses_tirants_eau(navire)
    if x_av == x_ar:
        return (hap_m + hfp_m) / 2
    t = (x_m - x_ar) / (x_av - x_ar)
    return hap_m + t * (hfp_m - hap_m)


def classement_envahissement(navire, hap_m, hfp_m):
    """Toutes les ouvertures du dossier, de la plus tôt immergée à la plus
    tardive : [{repere, fonction, x_m, y_m, z_m, tirant_local_m,
    franc_bord_m, angle_deg}].

    Même géométrie que `downflooding_angle` — muraille verticale au droit du
    point, franc-bord local pris sur la pente de flottaison —, mais rendue
    ouverture par ouverture : le dossier ne retient que la première, alors
    que le bord veut voir laquelle vient ensuite, et de combien (D-59). Une
    ouverture dans l'axe (demi-largeur nulle) n'a pas d'angle et n'est pas
    classée : elle est rendue avec `angle_deg` à None, en fin de liste.
    """
    out = []
    for p in navire.points_envahissement:
        try:
            x, y, z = float(p["X_m"]), float(p["Y_m"]), float(p["Z_m"])
        except (KeyError, TypeError, ValueError):
            continue
        d_local = local_draft(navire, x, hap_m, hfp_m)
        franc_bord = z - d_local
        demi_largeur = abs(y)
        angle = (math.degrees(math.atan2(max(franc_bord, 0.0), demi_largeur))
                 if demi_largeur > 1e-6 else None)
        out.append({"repere": p.get("Repere") or "", "fonction": p.get("Fonction") or "",
                    "x_m": x, "y_m": y, "z_m": z, "tirant_local_m": d_local,
                    "franc_bord_m": franc_bord, "angle_deg": angle})
    # les sans-angle (dans l'axe) à la fin : on ne les fait pas passer pour
    # les plus exposées sous prétexte qu'on ne sait pas les compter
    out.sort(key=lambda r: (r["angle_deg"] is None, r["angle_deg"] or 0.0))
    return out


def downflooding_angle(navire, hap_m, hfp_m):
    """Angle de gîte d'envahissement (première ouverture immergée), approché
    géométriquement point par point : arctan(franc-bord local / demi-largeur),
    ce qui suppose une muraille verticale au droit du point (approximation
    usuelle en l'absence de forme de coque numérisée). Retourne (angle_deg,
    point_repere) pour le point le plus contraignant, ou (None, None) si la
    table de points d'envahissement du navire est vide.

    L'angle est compté depuis la **verticale**. Avec une gîte permanente, la
    marge réelle du côté où le navire est couché est réduite d'autant : c'est
    à l'appelant d'en tenir compte (voir `criteria.evaluate_general`, qui
    ramène θf à la gîte d'équilibre).

    Le franc-bord local passe par `local_draft`, donc par la pente de
    flottaison : sur un dossier sans perpendiculaires, elle est prise sur les
    repères peints et l'angle rendu n'est qu'approché. Le couple rendu ne le
    dit pas — demander `source_tirants_eau(navire)`."""
    for r in classement_envahissement(navire, hap_m, hfp_m):
        if r["angle_deg"] is not None:
            return r["angle_deg"], r["repere"]
    return None, None
