# -*- coding: utf-8 -*-
"""Critère météo (vent de travers + roulis), IMO IS Code 2008 Part A §2.3.

Les tables numériques ci-dessous (X1, X2, k, s) et la pression de vent P sont
des CONSTANTES RÉGLEMENTAIRES universelles du code IMO — au même titre que les
seuils d'aire 0.055/0.090/0.030 m.rad du critère général — pas des données
propres à un navire ; elles ont donc leur place dans le moteur, contrairement
aux tables hydrostatiques/KN/capacités qui elles viennent du navire virtuel.

Toutes les grandeurs propres au navire (L, B, d, Cb, GM, aire et centre de la
surface au vent, aire et centre du plan de dérive immergé, quilles anti-roulis)
sont reçues en paramètres — voir carene.core.condition pour leur origine.
"""
import math
from dataclasses import dataclass, field

from .interp import interp1d_linear
from .stability import gz_at, gz_residuel_at

G = 9.81  # m/s^2

_X1_TABLE = [(2.4, 1.00), (2.5, 0.98), (2.6, 0.96), (2.7, 0.95), (2.8, 0.93),
             (2.9, 0.91), (3.0, 0.90), (3.1, 0.88), (3.2, 0.86), (3.3, 0.84),
             (3.4, 0.82), (3.5, 0.80)]

_X2_TABLE = [(0.45, 0.75), (0.50, 0.82), (0.55, 0.89), (0.60, 0.95),
             (0.65, 0.97), (0.70, 1.00)]

_K_TABLE = [(0.0, 1.00), (1.0, 0.98), (1.5, 0.95), (2.0, 0.88), (2.5, 0.79),
            (3.0, 0.74), (3.5, 0.72), (4.0, 0.70)]

# Table 2.3.4-4 : le texte s'arrête à « T = 20 s et au-delà → s = 0,035 ».
# Les lignes 22 à 30 s qui figuraient ici prolongeaient la table vers des
# valeurs plus faibles, donc un angle de roulis plus petit et un critère plus
# facile à passer : c'est un prolongement inventé, et non conservatif. On
# écrête à 0,035 au-delà de 20 s, ce que dit le texte.
_S_TABLE = [(6, 0.100), (7, 0.098), (8, 0.093), (12, 0.065), (14, 0.053),
            (16, 0.044), (18, 0.038), (20, 0.035)]


def _table(tables, nom, defaut):
    """Une table de facteurs : celle du fichier de réglementation s'il la
    donne (D-79), celle de ce module sinon (la même, tant que le texte n'a pas
    changé)."""
    t = (tables or {}).get(nom)
    return [tuple(x) for x in t] if t else defaut


def _clamped(table, x):
    """Lecture d'une table de facteurs du code IMO, écrêtée à ses bornes.

    L'écrêtage est ici **voulu et réglementaire** : le texte donne des valeurs
    au-delà desquelles le facteur ne varie plus. C'est le seul endroit du
    moteur où geler la valeur en bord de table est correct."""
    xs = [t[0] for t in table]
    ys = [t[1] for t in table]
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    return interp1d_linear(xs, ys, x, hors_bornes="ecrete")


def x1_factor(b_over_d):
    return _clamped(_X1_TABLE, b_over_d)


def x2_factor(cb):
    return _clamped(_X2_TABLE, cb)


def k_factor(ak_pct_lb):
    return _clamped(_K_TABLE, ak_pct_lb)


def s_factor(roll_period_s):
    return _clamped(_S_TABLE, roll_period_s)


def roll_period_s(beam_m, draft_m, lwl_m, gm_m):
    """T = 2 C B / sqrt(GM) (s), C = 0.373 + 0.023(B/d) - 0.043(Lwl/100).

    Rend None si la formule n'a pas de sens (GM nul ou négatif, tirant d'eau
    nul) : un navire à GM ≤ 0 n'a pas de période de roulis, et renvoyer un
    nombre ou lever une exception de calcul serait pire que de le dire."""
    if draft_m <= 0 or gm_m <= 0:
        return None
    c = 0.373 + 0.023 * (beam_m / draft_m) - 0.043 * (lwl_m / 100.0)
    return 2 * c * beam_m / math.sqrt(gm_m)


def roll_angle_windward_deg(k, x1, x2, r, s):
    """phi1 = 109 k X1 X2 sqrt(r s) (deg)."""
    return 109.0 * k * x1 * x2 * math.sqrt(max(r, 0.0) * s)


def wind_lever_m(pressure_pa, area_m2, z_m, displacement_t):
    """lw = P A Z / (1000 g Delta) (m)."""
    return pressure_pa * area_m2 * z_m / (1000.0 * G * displacement_t)


@dataclass
class WeatherResult:
    theta0_deg: float
    theta1_deg: float
    theta2_deg: float
    theta_c_deg: float
    theta_f_deg: float
    lw1_m: float
    lw2_m: float
    area_a: float
    area_b: float
    roll_period_s: float
    ok_area: bool
    ok_theta0: bool
    details: dict
    # False : le critère n'a pas pu être évalué (GM ≤ 0…). `messages` dit
    # pourquoi. Un critère non évaluable n'est pas un critère satisfait :
    # ok_area et ok_theta0 valent alors False.
    evaluable: bool = True
    messages: list = field(default_factory=list)
    # True : le bras de vent établi lw1 n'est JAMAIS rattrapé par GZ — le
    # navire ne tient pas le vent permanent. Ce n'est pas un calcul qui n'a
    # pas abouti : c'est le pire résultat possible, et il se dit NON
    # CONFORME, pas « non évaluable » (R-5, D-78).
    chavire: bool = False
    # la borne de θ0 réellement appliquée : 16°, ou 80 % de l'angle
    # d'immersion du livet s'il est plus petit (IS 2008 A/2.3.1.2, R-3)
    limite_theta0_deg: float = 16.0
    limite_theta0_source: str = ""


class _CourbeCote:
    """Courbe GZ vue **du côté où le navire gîte**, en angle depuis la
    verticale (positif vers ce côté).

    Le critère météo était appliqué à la courbe physique, de 0° vers +60°.
    Avec une bande sur bâbord (TCG < 0), la gîte d'équilibre est négative et
    le bras de vent n'est jamais « rattrapé » du côté positif : le critère
    concluait à tort que le navire ne tient pas le vent permanent. On fait
    comme `criteria.evaluate_general` : on regarde du côté de la gîte
    (`gz_res.sens`, `gz_res.origine_deg`), là où le vent aggrave la bande.

    - au-delà de la gîte d'équilibre, on lit la courbe résiduelle, calculée
      sur les pantocarènes et jamais prolongée ;
    - en deçà (entre la verticale et l'équilibre, et au vent), on lit la
      courbe physique, symétrisée si besoin (GZ(−φ) = −GZ(φ)).

    Sur un navire droit (origine 0°, sens +1), c'est la courbe physique
    telle quelle : les résultats sont inchangés.
    """

    def __init__(self, gz_res):
        self.res = gz_res
        self.sens = 1 if gz_res.sens >= 0 else -1
        self.origine = abs(gz_res.origine_deg or 0.0)
        self.droit = (self.origine < 1e-9 and self.sens == 1)
        self.residuel = bool(gz_res.heel_residuel_deg) and not self.droit
        # étendue réellement calculée, dans ce repère
        h0, h1 = gz_res.heel_deg[0], gz_res.heel_deg[-1]
        self.au_vent_min = h0 if self.sens == 1 else -h1
        # jusqu'où la courbe physique est tracée de ce côté (entre la
        # verticale et la gîte d'équilibre, c'est elle qui est lue)
        self.physique_max = h1 if self.sens == 1 else -h0
        if self.residuel:
            self.sous_le_vent_max = self.origine + gz_res.residuel_max_deg
        else:
            self.sous_le_vent_max = h1 if self.sens == 1 else -h0
        self.angle_gz_max = self.sens * gz_res.angle_gz_max_absolu_deg

    def gz(self, phi_deg):
        if self.residuel and phi_deg >= self.origine - 1e-9:
            return gz_residuel_at(self.res, phi_deg - self.origine)
        return self.sens * gz_at(self.res, self.sens * phi_deg)

    def gz_max(self):
        return self.res.gz_max_m


def _find_crossing(courbe, lever, start_deg, direction, stop_deg, step=0.05):
    """Premier angle où GZ(heel) coupe la droite lever, en partant de
    start_deg et en avançant de `direction` (+1 ou -1) jusqu'à stop_deg."""
    h = start_deg
    prev = courbe.gz(h) - lever
    n = int(abs(stop_deg - start_deg) / step)
    for _ in range(n):
        h2 = h + direction * step
        cur = courbe.gz(h2) - lever
        if prev == 0:
            return h
        if prev * cur < 0:
            return h - prev * (h2 - h) / (cur - prev)
        h, prev = h2, cur
    return None


def evaluate(navire, gz_res, equilibre, displacement_t,
             windage_area_m2, windage_center_v_m, lateral_plane_center_v_m,
             cb, beam_m, lwl_m, ak_pct_lb=0.0, theta_f_deg=None,
             pressure_pa=None, critere=None, tables=None):
    """Applique le critère météo complet (IS Code 2008 §2.3) à une courbe GZ
    déjà calculée (voir carene.core.stability.gz_curve).

    `critere` et `tables` viennent du fichier de la réglementation (D-79) :
    pression, bornes, facteur de rafale, tables X1, X2, k, s. Sans eux, le
    dossier du navire (`criteres.critere_meteo`) et les tables de ce module."""
    if critere is None:
        critere = navire.criteres.get("critere_meteo", {})
    p = pressure_pa if pressure_pa is not None else critere.get("pression_vent_pa", 504.0)
    d = equilibre.draft_m
    z = windage_center_v_m - lateral_plane_center_v_m
    # La pression selon h (Code IS 2008, partie B, § 2.1.4.2, navires de
    # pêche de 24 à 45 m) : h est la hauteur du centre de la surface au vent
    # au-dessus de la flottaison ; entre deux lignes de la table, interpolée ;
    # hors de la table, sa première ou sa dernière valeur.
    h_vent = None
    table_p = critere.get("pression_vent_selon_h_pa") if pressure_pa is None else None
    if table_p:
        h_vent = float(windage_center_v_m) - float(d)
        p = _clamped(sorted((float(a), float(b)) for a, b in table_p), h_vent)
    lw1 = wind_lever_m(p, windage_area_m2, z, displacement_t)
    lw2 = float(critere.get("facteur_rafale", 1.5)) * lw1

    gm = gz_res.gm_corrige_m
    og = gz_res.kg_effectif_m - d
    # IS 2008 A/2.3.1.2 : θ0 ≤ 16° OU 80 % de l'angle d'immersion du livet,
    # LE PLUS PETIT des deux. Seuls les 16° étaient appliqués (R-3). L'angle
    # du livet : celui du dossier s'il le donne (`critere_meteo.
    # angle_immersion_livet_deg`), sinon estimé depuis le creux et la largeur
    # — et dit estimé.
    borne_16 = float(critere.get("angle_gite_vent_stable_deg_max", 16.0))
    # `fraction_angle_immersion_livet` à null : la limite du livet est levée
    # (bois en pontée, Code IS 2008, partie A, § 3.3.2.4 — seuls les 16°)
    fraction_livet = critere.get("fraction_angle_immersion_livet", 0.80)
    fraction_livet = None if fraction_livet is None else float(fraction_livet)
    livet = critere.get("angle_immersion_livet_deg")
    source_livet = "du dossier"
    if fraction_livet is None:
        livet = None
    elif not livet:
        from .criteria import angle_immersion_pont_deg
        livet = angle_immersion_pont_deg(navire, d)
        source_livet = "estimé"
    freeboard_limit = borne_16
    limite_source = "16° réglementaires"
    if livet:
        borne_livet = fraction_livet * float(livet)
        if borne_livet < borne_16:
            freeboard_limit = borne_livet
            limite_source = (f"{fraction_livet * 100:.0f} % de l'angle d'immersion du "
                             f"livet ({float(livet):.1f}°, {source_livet})")

    def sans_objet(motif, chavire=False):
        return WeatherResult(
            theta0_deg=None, theta1_deg=None, theta2_deg=None, theta_c_deg=None,
            theta_f_deg=theta_f_deg, lw1_m=lw1, lw2_m=lw2, area_a=float("nan"),
            area_b=float("nan"), roll_period_s=None, ok_area=False,
            ok_theta0=False, evaluable=chavire, messages=[motif],
            details=dict(z_m=z, gm_corrige_m=gm, og_m=og,
                          windage_area_m2=windage_area_m2,
                          gz_max_m=gz_res.gz_max_m),
            chavire=chavire, limite_theta0_deg=freeboard_limit,
            limite_theta0_source=limite_source)

    if gm <= 0:
        return sans_objet(
            f"GM corrigé {gm:+.3f} m : le navire n'est pas stable à la "
            "flottaison droite, le critère météo est sans objet.")

    # Courbe lue du côté où le navire gîte (voir _CourbeCote) : les angles
    # θ0, θ1, θ2 sont comptés depuis la verticale, positifs vers ce côté.
    courbe = _CourbeCote(gz_res)
    messages = []
    if not courbe.droit:
        messages.append(
            f"Gîte d'équilibre {gz_res.origine_deg:+.1f}° : le critère est "
            "évalué du côté où le navire gîte, le vent aggravant la bande ; "
            "les angles sont comptés depuis la verticale.")
        if courbe.residuel and courbe.origine > courbe.physique_max + 1e-9:
            messages.append(
                f"La courbe GZ n'est tracée que jusqu'à "
                f"{courbe.sens * courbe.physique_max:+.1f}° de ce côté, en deçà de la gîte "
                "d'équilibre : entre les deux, elle est prolongée, non "
                "calculée. Recalculez la courbe plus bas.")

    # θ0 : gîte sous le vent établi. Pas d'intersection = le bras de vent
    # dépasse le GZ maximal, donc le navire ne tient pas le vent établi. C'est
    # le pire des cas, et l'écrire « θ0 = 0°, conforme » était un contresens.
    theta0 = _find_crossing(courbe, lw1, 0.0, +1, 60.0)
    if theta0 is None:
        return sans_objet(
            f"Le bras de vent établi ({lw1:.3f} m) n'est jamais rattrapé par "
            f"GZ (max {gz_res.gz_max_m:.3f} m) : le navire ne tient pas le "
            "vent permanent. Aucune gîte d'équilibre sous voilure.",
            chavire=True)

    r = 0.73 + 0.6 * og / d
    x1 = _clamped(_table(tables, "X1_B_sur_d", _X1_TABLE), beam_m / d)
    x2 = _clamped(_table(tables, "X2_Cb", _X2_TABLE), cb)
    k = _clamped(_table(tables, "k_Ak_pct_LB", _K_TABLE), ak_pct_lb)
    t_roll = roll_period_s(beam_m, d, lwl_m, gm)
    if t_roll is None:
        return sans_objet("Période de roulis non calculable "
                          "(GM ≤ 0 ou tirant d'eau nul).")
    s = _clamped(_table(tables, "s_periode_s", _S_TABLE), t_roll)
    theta1 = roll_angle_windward_deg(k, x1, x2, r, s)

    # theta_c = second intercept GZ/lw2 (GZ redescendant sous lw2 après son
    # maximum) : on part du sommet de la courbe pour ne pas retrouver la
    # première intersection (GZ montant à travers lw2, juste après theta0).
    theta_c = _find_crossing(courbe, lw2, courbe.angle_gz_max, +1,
                              courbe.sous_le_vent_max - 0.1)
    candidates = [float(critere.get("angle_theta2_max_deg", 50.0))]
    if theta_c is not None:
        candidates.append(theta_c)
    if theta_f_deg is not None:
        candidates.append(theta_f_deg)
    theta2 = min(candidates)

    debut_a = theta0 - theta1
    if debut_a < courbe.au_vent_min - 1e-9:
        # l'aire a démarre sous l'étendue calculée : la lire là reviendrait à
        # prolonger la courbe GZ en silence
        messages.append(
            f"L'aire a commence à {debut_a:.1f}°, sous l'étendue calculée de "
            f"la courbe GZ ({courbe.au_vent_min:.1f}°) : la partie manquante "
            "est prolongée, non mesurée. Recalculez la courbe plus bas.")
    if theta2 > courbe.sous_le_vent_max + 1e-9:
        messages.append(
            f"L'aire b s'étend jusqu'à {theta2:.1f}°, au-delà de l'étendue "
            f"calculée de la courbe GZ ({courbe.sous_le_vent_max:.1f}°) : la "
            "partie manquante est prolongée, non mesurée.")
    # LES AIRES a ET b SONT BORNÉES PAR lw2 (IS 2008, fig. 2.3.1) : a est la
    # surface où lw2 passe AU-DESSUS de GZ, de θ0 − θ1 jusqu'à la première
    # intersection de GZ avec lw2 ; b celle où GZ repasse au-dessus, de là
    # jusqu'à θ2. Elles étaient coupées à θ0 (intersection avec lw1) : le
    # verdict b ≥ a était le même — la différence b − a ne change pas —,
    # mais les deux aires affichées étaient trop petites de la même quantité
    # (R-4, D-78 ; recueil de référence, cas 01 : a 0,0481 / b 0,2224).
    theta_lw2 = _find_crossing(courbe, lw2, theta0, +1, theta2)
    fin_a = theta_lw2 if theta_lw2 is not None else theta2
    area_a = _area_between(courbe, lw2, debut_a, fin_a, gz_minus_lever=False)
    area_b = (_area_between(courbe, lw2, theta_lw2, theta2, gz_minus_lever=True)
              if theta_lw2 is not None and theta2 > theta_lw2 else 0.0)
    if h_vent is not None:
        messages.append(f"Pression du vent P = {p:.0f} Pa, lue dans la table de la "
                        f"réglementation pour h = {h_vent:.2f} m (hauteur du centre de "
                        "la surface au vent au-dessus de la flottaison).")
    if fraction_livet is None:
        messages.append("Limite de 80 % de l'angle d'immersion du livet levée par la "
                        "réglementation retenue : seuls les 16° bornent la gîte sous "
                        "vent établi.")
    if freeboard_limit < borne_16:
        messages.append(f"Gîte sous vent établi bornée à {freeboard_limit:.1f}° : "
                        f"{limite_source}, plus petit que les 16°.")

    return WeatherResult(
        theta0_deg=theta0, theta1_deg=theta1, theta2_deg=theta2, theta_c_deg=theta_c,
        theta_f_deg=theta_f_deg, lw1_m=lw1, lw2_m=lw2, area_a=area_a, area_b=area_b,
        roll_period_s=t_roll, ok_area=(area_b >= area_a), ok_theta0=(theta0 <= freeboard_limit),
        evaluable=True, messages=messages,
        details=dict(z_m=z, gm_corrige_m=gm, og_m=og, r=r, x1=x1, x2=x2, k=k, s=s,
                      windage_area_m2=windage_area_m2, theta_lw2_deg=theta_lw2,
                      cb=cb, lwl_m=lwl_m, b_sur_d=beam_m / d,
                      p_pa=p, h_vent_m=h_vent),
        limite_theta0_deg=freeboard_limit, limite_theta0_source=limite_source)


def _area_between(courbe, lever, a_deg, b_deg, gz_minus_lever, n=200):
    """Aire entre la courbe GZ (vue du côté de la gîte, `_CourbeCote`) et la
    droite horizontale `lever`, entre a_deg et b_deg (a_deg peut être < 0).
    gz_minus_lever=True -> (GZ - lever) [aire b], False -> (lever - GZ)
    [aire a]."""
    import numpy as np
    if n % 2:
        n += 1
    xs = np.linspace(a_deg, b_deg, n + 1)
    gz = np.array([courbe.gz(float(x)) for x in xs])
    ys = (gz - lever) if gz_minus_lever else (lever - gz)
    h = math.radians(xs[1] - xs[0])
    area = ys[0] + ys[-1] + 4 * sum(ys[1:-1:2]) + 2 * sum(ys[2:-1:2])
    return float(area * h / 3)
