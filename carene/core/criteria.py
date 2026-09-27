# -*- coding: utf-8 -*-
"""Critères réglementaires généraux (IMO IS Code 2008 §2.2, BV NR500) appliqués
à une courbe GZ déjà calculée. Les seuils numériques sont lus dans navire.json
(section "criteres") — pas codés en dur ici — puisqu'un autre navire pourrait
relever d'un jeu de règles légèrement différent (pavillon, société de
classification...). Seules les formules de calcul (aires, GZmax...) sont
génériques.
"""
from dataclasses import dataclass, field

import math

import numpy as np

from .interp import pchip_eval
from .stability import aire_residuelle, gz_residuel_at, source_tirants_eau


@dataclass
class CriterionCheck:
    code: str
    libelle: str
    valeur: float
    seuil: float
    comparaison: str   # ">=" ou "<="
    ok: bool
    unite: str = ""
    evaluable: bool = True     # False : la valeur n'a pas pu être calculée
    # Sous quel titre cette ligne se range dans le tableau des critères. "" =
    # les critères généraux, ceux qui s'appliquent quoi qu'il arrive. Les
    # critères de vent, eux, dépendent de la voilure portée : ils arrivent sous
    # leur propre titre pour qu'on ne les lise pas comme des critères généraux.
    groupe: str = ""
    # True : ligne d'INFORMATION, pas un critère à seuil. Le dossier de
    # stabilité en imprime (la force de vent admissible, la pression
    # correspondante) : ce sont des résultats du calcul, pas des épreuves à
    # passer, et elles ne pèsent donc pas dans le verdict.
    information: bool = False


@dataclass
class CriteriaReport:
    checks: list = field(default_factory=list)
    messages: list = field(default_factory=list)

    @property
    def criteres(self):
        """Les seules lignes qui font verdict : les lignes d'information n'en
        sont pas."""
        return [c for c in self.checks if not c.information]

    @property
    def ok(self):
        """Tous les critères sont-ils satisfaits **et évaluables** ? Un critère
        non évaluable n'est pas un critère satisfait."""
        criteres = self.criteres
        return bool(criteres) and all(c.ok and c.evaluable for c in criteres)

    @property
    def verdict(self):
        """Le verdict en un mot (D-78) :

        - « NON ÉVALUABLE » : aucun critère ;
        - « NON CONFORME » : au moins un critère évalué échoue ;
        - « INCOMPLET » : tout ce qui a pu être évalué passe, mais un critère
          n'a pas pu l'être (critère météo sans surface au vent…) — ce n'est
          PAS un « CONFORME », et ce n'est pas un échec non plus ;
        - « CONFORME » : tout est évalué, tout passe."""
        criteres = self.criteres
        if not criteres:
            return "NON ÉVALUABLE"
        if any(c.evaluable and not c.ok for c in criteres):
            return "NON CONFORME"
        if any(not c.evaluable for c in criteres):
            return "INCOMPLET"
        return "CONFORME"

    def add(self, code, libelle, valeur, seuil, comparaison, unite="",
            groupe="", information=False):
        # un NaN n'est ni conforme ni non conforme : c'est un calcul qui n'a
        # pas abouti, et le dire vaut mieux que d'afficher « NON CONFORME »
        evaluable = valeur == valeur and valeur is not None \
            and not math.isinf(valeur)
        if information:
            # une information n'a pas de verdict : elle est « ok » pour que
            # rien ne la peigne en rouge, et `criteres` l'écarte du compte
            ok = True
        elif not evaluable:
            ok = False
        elif comparaison == ">=":
            ok = valeur >= seuil - 1e-9
        else:
            ok = valeur <= seuil + 1e-9
        self.checks.append(CriterionCheck(code, libelle, valeur, seuil,
                                          comparaison, ok, unite, evaluable,
                                          groupe, information))

    def add_information(self, code, libelle, valeur, unite="", groupe=""):
        """Une valeur que le dossier imprime sans lui opposer de seuil."""
        self.add(code, libelle, valeur, float("nan"), "=", unite,
                 groupe=groupe, information=True)

    def fusionner(self, autre):
        """Verse les lignes et les messages d'un autre rapport dans celui-ci.

        C'est ainsi que les critères de vent (qui dépendent de la voilure
        portée) rejoignent les critères généraux : un seul tableau à l'écran,
        un seul verdict au bandeau, et un critère de vent non conforme rend
        le point non conforme."""
        if autre is None:
            return self
        self.checks.extend(autre.checks)
        for m in autre.messages:
            if m not in self.messages:
                self.messages.append(m)
        return self


def evaluate_general(navire, gz_res, theta_f_deg=None, extra_seuils=None):
    """Critères généraux IS2008 (aires, GZmax, angle de GZmax, GM0) + NR500
    (GM0 ≥ 0,30 m pour un navire à voile) si présent dans navire.json.

    Deux points sur lesquels ce module ne suit pas la lecture naïve du texte :

    - **origine des aires** : elles sont mesurées depuis la *gîte d'équilibre*
      et du côté vers lequel le navire est couché (courbe résiduelle de
      `gz_curve`), et non depuis 0°. Sur un navire droit c'est rigoureusement
      identique ; avec une bande permanente, intégrer depuis 0° donnerait des
      aires optimistes du côté opposé à la bande ;
    - **plafond des aires** : l'aire dite « 0-40° » s'arrête à θf si l'angle
      d'envahissement est inférieur à 40°, et l'aire « 30-40° » devient
      30°-θf. Passez `theta_f_deg` (angle depuis la verticale, tel que rendu
      par `stability.downflooding_angle`) pour que ce plafond s'applique ; sans
      lui, les bornes réglementaires nominales sont utilisées et un message le
      signale.
    """
    seuils = dict(navire.criteres.get("is2008_general", {}))
    if extra_seuils:
        seuils.update(extra_seuils)
    report = CriteriaReport()

    if gz_res.origine_deg is None or not gz_res.heel_residuel_deg:
        # Rien à mesurer depuis l'équilibre — mais ce n'est pas « sans
        # objet » : c'est le pire des cas. Le GM, qui ne dépend pas de la
        # courbe, se dit ; et l'absence d'équilibre est un critère échoué,
        # pas un tableau vide (R-6, D-78).
        report.add("IS2008_GM", "GM0 corrigé", gz_res.gm_corrige_m,
                   seuils.get("gm0_corrige_m_min", 0.150), ">=", "m")
        report.add("EQUILIBRE", "Équilibre stable (le navire se redresse)",
                   0.0, 1.0, ">=", "")
        report.messages.append(
            "Aucune gîte d'équilibre stable dans le domaine des pantocarènes : "
            "le navire ne se redresse pas. Les aires et le GZ ne se mesurent "
            "pas — le point est NON CONFORME.")
        return report

    # θf est compté depuis la verticale ; la bande a déjà consommé une partie
    # de la marge du côté où le navire est couché
    x_f = None
    if theta_f_deg is not None:
        # R-7 : θf n'est pas lu dans le dossier, il est approché point par
        # point (franc-bord local / demi-largeur, muraille verticale). Il
        # plafonne les aires : on le dit toujours.
        report.messages.append(
            f"Angle d'envahissement θf = {float(theta_f_deg):.1f}° approché "
            "géométriquement (franc-bord local / demi-largeur, muraille "
            "verticale) : il plafonne les aires 0-40° et 30-40°.")
        # `downflooding_angle` mesure le franc-bord local sur la pente de
        # flottaison ; sans perpendiculaires au dossier, celle-ci est prise
        # sur les repères peints, qui sont 5 m plus courts sur le navire de
        # référence — soit
        # près de 9 % d'erreur sur la pente, donc sur θf. Le couple rendu ne
        # porte pas ce drapeau : on le redemande au navire, et on le dit.
        source = source_tirants_eau(navire)
        if source != "perpendiculaires":
            report.messages.append(
                "Angle d'envahissement calculé sur les repères peints, pas "
                "sur les perpendiculaires : approché."
                + ("" if source == "reperes" else
                   " Le dossier ne donne ni les unes ni les autres : la "
                   "flottaison est prise horizontale."))
        x_f = float(theta_f_deg) - abs(gz_res.origine_deg)
        if x_f <= 0:
            report.add("IS2008_GM", "GM0 corrigé", gz_res.gm_corrige_m,
                       seuils.get("gm0_corrige_m_min", 0.150), ">=", "m")
            report.add("IS2008_THETAF",
                       "Gîte permanente en deçà de l'angle d'envahissement",
                       float(theta_f_deg), abs(gz_res.origine_deg), ">=", "deg")
            report.messages.append(
                f"Angle d'envahissement θf = {theta_f_deg:.1f}° déjà atteint "
                f"par la gîte permanente ({gz_res.origine_deg:+.1f}°).")
            return report

    x30 = 30.0
    x40 = 40.0 if x_f is None else min(40.0, x_f)
    borne = f"{x40:.0f}°" + ("" if x_f is None or x40 >= 40.0 else " (θf)")
    if gz_res.residuel_max_deg < x40 - 1e-9:
        # la courbe résiduelle s'arrête avant la borne d'intégration : plutôt
        # que de prolonger les pantocarènes, on refuse d'évaluer
        report.messages.append(
            f"La courbe résiduelle s'arrête à {gz_res.residuel_max_deg:.1f}° "
            f"(dernier angle tabulé des pantocarènes moins la gîte "
            f"d'équilibre {gz_res.origine_deg:+.1f}°) : l'aire jusqu'à "
            f"{borne} ne peut pas être mesurée sans prolonger la table.")
    # on ne mentionne l'origine que si elle se voit : sur un navire droit, le
    # libellé réglementaire habituel est le bon
    depuis = ("" if abs(gz_res.origine_deg) < 0.05
              else f" depuis la gîte d'équilibre {gz_res.origine_deg:+.1f}°")

    a30 = aire_residuelle(gz_res, 0.0, x30)
    a40 = aire_residuelle(gz_res, 0.0, x40)
    a3040 = aire_residuelle(gz_res, x30, x40) if x40 > x30 else float("nan")
    report.add("IS2008_A1", f"Aire 0°-30°{depuis}", a30,
               seuils.get("aire_0_30_m_rad_min", 0.055), ">=", "m.rad")
    report.add("IS2008_A2", f"Aire 0°-{borne}{depuis}", a40,
               seuils.get("aire_0_40_m_rad_min", 0.090), ">=", "m.rad")
    report.add("IS2008_A3", f"Aire 30°-{borne}{depuis}", a3040,
               seuils.get("aire_30_40_m_rad_min", 0.030), ">=", "m.rad")

    # IS2008 §2.2.2 : « GZ d'au moins 0,20 m à une gîte égale ou supérieure à
    # 30° ». On teste donc le maximum atteint **au-delà de 30°**, et non le
    # maximum global : une courbe qui culmine à 25° puis retombe ne satisfait
    # pas le critère, même si son sommet dépasse le seuil.
    gz_au_dela_30 = _max_au_dela(gz_res, x30)
    report.add("IS2008_GZ", "GZ maximal au-delà de 30°", gz_au_dela_30,
               seuils.get("gz_max_m_min", 0.200), ">=", "m")
    report.add("IS2008_ANG", f"Angle du GZmax{depuis}", gz_res.angle_gz_max_deg,
               seuils.get("angle_gz_max_deg_min", 25.0), ">=", "deg")
    report.add("IS2008_GM", "GM0 corrigé", gz_res.gm_corrige_m,
               seuils.get("gm0_corrige_m_min", 0.150), ">=", "m")

    nr500 = navire.criteres.get("nr500_voile")
    if nr500:
        report.add("NR500_GM", "GM0 corrigé (NR500 voile)", gz_res.gm_corrige_m,
                    nr500.get("gm0_corrige_m_min", 0.30), ">=", "m")

    if theta_f_deg is None:
        report.messages.append(
            "Angle d'envahissement non fourni : les aires sont plafonnées à "
            "40° nominal. Si θf est inférieur à 40°, ces aires sont "
            "surestimées.")
    if not gz_res.dans_domaine_kn:
        report.messages.append(
            "Assiette ou déplacement hors du domaine de la table des "
            "pantocarènes : les KN sont lus en bord de table, la courbe GZ et "
            "tout ce qui en découle sont sans valeur réglementaire.")
    return report


def _max_au_dela(gz_res, x_min_deg, pas=0.5):
    """Plus grand GZ résiduel atteint au-delà d'un angle donné.

    Le balayage se fait d'un seul appel PCHIP : point par point, la spline
    recalculait ses pentes sur toute la courbe à chaque pas, pour un résultat
    rigoureusement identique. Le dernier angle tabulé est toujours du balayage,
    même quand le pas ne tombe pas juste — c'est souvent là que la courbe
    culmine, et l'écarter aurait changé le critère.
    """
    xs = gz_res.heel_residuel_deg
    if not xs:
        return float("nan")
    fin = xs[-1]
    if x_min_deg > fin:
        return float("nan")
    balayage = np.append(np.arange(x_min_deg, fin, pas), fin)
    return float(np.max(pchip_eval(xs, gz_res.gz_residuel_m, balayage)))


def _nr500_gm_et_gz(report, gz_res, seuils, groupe=""):
    """Les deux premières lignes du bloc NR500 sous voile : GM corrigé, puis
    GZ au point de référence. Communes au critère partiel
    (`evaluate_nr500_sous_voile`) et au critère complet
    (`evaluate_nr500_voilier`) : les écrire deux fois, c'est le jour où l'une
    des deux part à la dérive sans que rien ne le dise."""
    report.add("NR500_VOILE_GM", "G'M (GM corrigé)", gz_res.gm_corrige_m,
               seuils.get("gm0_corrige_m_min", 0.30), ">=", "m", groupe=groupe)
    # Le point de référence est le GZmax si son angle atteint déjà le seuil,
    # sinon GZ pris au seuil lui-même (ex NR500 : "GZ max or 50°, la plus
    # grande des deux angles") — ce n'est pas un critère d'angle indépendant,
    # juste le choix du point testé ci-dessous.
    # angles comptés depuis la gîte d'équilibre, comme les aires
    seuil_angle = seuils.get("angle_gzmax_deg_min", 50.0)
    if gz_res.angle_gz_max_deg >= seuil_angle:
        gz_ref = gz_res.gz_max_m
    elif gz_res.residuel_max_deg < seuil_angle - 1e-9:
        # la courbe résiduelle s'arrête avant l'angle de référence :
        # `gz_residuel_at` prolongerait les pantocarènes, et une valeur
        # extrapolée n'a pas à être présentée comme un GZ à 50°
        gz_ref = float("nan")
        report.messages.append(
            f"GZ à {seuil_angle:.0f}° non évaluable : courbe résiduelle trop "
            f"courte (jusqu'à {gz_res.residuel_max_deg:.1f}°).")
    else:
        gz_ref = gz_residuel_at(gz_res, seuil_angle)
    report.add("NR500_VOILE_GZ",
               f"GZ au point de référence (GZmax ou {seuil_angle:.0f}°)",
               gz_ref, seuils.get("gz_a_50deg_ou_gzmax_m_min", 0.5), ">=", "m",
               groupe=groupe)
    return report


def evaluate_nr500_sous_voile(navire, gz_res, groupe=""):
    """Critère NR500 spécifique aux cas avec voilure déployée (cas 01d-f/02d-f
    du dossier de référence) : remplace le critère météo IS2008 standard pour ces
    conditions. GZ à 50° (ou GZmax si son angle est >= 50°) doit dépasser un
    seuil, et l'angle du GZmax doit atteindre 50° — seuils lus dans
    navire.json (section nr500_voile_sous_voile).

    C'est la MOITIÉ du critère du dossier : les deux lignes qui ne demandent
    que la courbe GZ. Les deux autres (angle statique sous vent, aire entre GZ
    et bras de vent) demandent la surface au vent de la voilure portée — voir
    `evaluate_nr500_voilier`, qui les ajoute."""
    seuils = navire.criteres.get("nr500_voile_sous_voile")
    if not seuils:
        return None
    report = CriteriaReport()
    if gz_res.origine_deg is None or not gz_res.heel_residuel_deg:
        report.messages.append(
            "Aucune gîte d'équilibre stable : critère sans objet.")
        return report
    return _nr500_gm_et_gz(report, gz_res, seuils, groupe)


def angle_immersion_pont_deg(navire, te_milieu_m):
    """Angle de gîte auquel le livet de pont touche l'eau, **estimé** depuis le
    creux sur quille et la largeur hors membres : arctan((D − d) / (B/2)).

    C'est une estimation, et elle doit toujours être présentée comme telle :
    elle suppose un pont plat et rectiligne, sans tonture ni bouge, et une
    muraille verticale au maître-couple. Sur le navire de
    référence, elle donne 30,8° au
    tirant d'eau d'été. Le recueil du bord, lui, imprime sur ses six cas sous
    voile « 90% of deck imm. = 72.000 » — un angle d'immersion de 80°, la
    borne de sa table de gîte, sans rapport avec un livet à 3,75 m au-dessus
    de l'eau (D-58). Quand le dossier donne ce chiffre
    (`criteres.nr500_voile_sous_voile.angle_immersion_pont_dossier_deg`),
    c'est lui que `evaluate_nr500_voilier` applique, en le disant « du
    dossier » ; l'estimation ne sert qu'à défaut. Dans les deux cas, sur
    le navire de référence, ce sont les 20° qui gouvernent.
    (Une version antérieure de ce
    commentaire prêtait au dossier un 31,3° : c'était l'abscisse d'un
    dégagement d'air, pas un angle.)

    Rend None si le dossier ne donne pas le creux ou la largeur : on ne
    fabrique pas un angle réglementaire à partir de rien."""
    dims = (getattr(navire, "manifest", None) or {}).get("dimensions", {})
    creux = dims.get("creux_sur_quille_m")
    largeur = dims.get("largeur_hors_membres_m")
    if not creux or not largeur:
        return None
    franc_bord = float(creux) - float(te_milieu_m)
    if franc_bord <= 0:
        return 0.0
    return math.degrees(math.atan2(franc_bord, float(largeur) / 2.0))


def evaluate_nr500_voilier(navire, gz_res, eq, displacement_t, vent,
                           theta_f_deg, angle_pont_deg=None, groupe="", seuils=None):
    """Le critère NR500 « Sailing Yachts » du dossier, en entier, pour UNE
    configuration de voilure.

    Le recueil du bord imprime quatre lignes, dans cet ordre :

    1. **G'M ≥ 0,300 m** ;
    2. **GZ maximal à 50° ou plus ≥ 0,500 m** (GZmax si son angle atteint 50°,
       GZ à 50° sinon) ;
    3. l'**angle statique sous vent**, borné à 20° et à 90 % de l'angle
       d'immersion du pont ;
    4. l'**aire entre la courbe GZ et le bras de levier de gîte sous vent**,
       de l'angle statique à l'angle d'envahissement, **≥ 0,065 m·rad**.

    LE POINT QUI SURPREND, et qu'il faut avoir en tête pour lire les chiffres :
    le bras de gîte sous vent vaut `lever(θ) = lever0 · cos²θ`, et le dossier
    ne se donne PAS une force de vent pour en déduire un angle — il fait
    l'inverse. Il **choisit** la force de vent qui amène exactement le navire à
    l'angle statique maximal admissible, et imprime cette force. Vérifié sur
    les six cas sous voile du navire de référence : les trois voilures du
    cas 01 donnent
    toutes `lever0 = 0,3081 m` et celles du cas 02 `0,2926 m`, à quatre
    décimales — ce qui n'a de sens que si l'angle, et non la force, est la
    donnée d'entrée.

    Par conséquent la **force de vent F** et la **pression correspondante
    F / aire au vent** sont des RÉSULTATS, pas des critères : ce sont les
    lignes d'information de ce rapport. Ce qu'elles disent au bord est :
    « dans cette voilure, ce point de chargement encaisse jusqu'à tant de
    newtons de vent travers avant d'atteindre son angle statique limite ».
    C'est la marge qu'il faut comparer au temps qu'il fait, et c'est pour cela
    qu'elles sont affichées plutôt que gardées dans le calcul.

    Paramètres : `vent` est le dict des cinq grandeurs rendu par
    `carene.core.voilure.ProfilsVent.surface_au_vent` ; `theta_f_deg` l'angle
    d'envahissement compté depuis la verticale
    (`stability.downflooding_angle`) ; `angle_pont_deg` l'angle d'immersion du
    pont, estimé depuis le creux et la largeur s'il n'est pas fourni.
    """
    from .weather import G, _CourbeCote

    # les seuils et conventions viennent de la réglementation retenue et du
    # dossier (D-79) ; sans eux, du dossier seul
    seuils = dict(seuils) if seuils is not None else \
        dict(navire.criteres.get("nr500_voile_sous_voile") or {})
    report = CriteriaReport()
    if gz_res.origine_deg is None or not gz_res.heel_residuel_deg:
        report.messages.append(
            "Aucune gîte d'équilibre stable : les critères sous voile sont "
            "sans objet.")
        return report

    _nr500_gm_et_gz(report, gz_res, seuils, groupe)

    # ------------------------------------------------ angle statique retenu
    theta_max = float(seuils.get("angle_statique_vent_deg_max", 20.0))
    fraction = float(seuils.get("fraction_angle_immersion_pont", 0.90))
    # l'angle d'immersion du pont : celui que le dossier imprime s'il le
    # donne (D-58), sinon l'estimation depuis le creux et la largeur
    du_dossier = seuils.get("angle_immersion_pont_dossier_deg")
    if angle_pont_deg is None and du_dossier:
        angle_pont_deg = float(du_dossier)
        estime = False
    else:
        if angle_pont_deg is None:
            angle_pont_deg = angle_immersion_pont_deg(navire, eq.draft_m)
        estime = angle_pont_deg is not None
    plafond_pont = None if angle_pont_deg is None else fraction * angle_pont_deg
    theta_s = theta_max if plafond_pont is None else min(theta_max, plafond_pont)
    gouverne = ("les 20° réglementaires"
                if plafond_pont is None or theta_max <= plafond_pont
                else f"{fraction * 100:.0f} % de l'angle d'immersion du pont")

    courbe = _CourbeCote(gz_res)
    if not courbe.droit:
        report.messages.append(
            f"Gîte d'équilibre {gz_res.origine_deg:+.1f}° : l'angle statique "
            "sous voile est compté depuis la verticale, du côté où le navire "
            "est déjà couché — la bande permanente mange la marge avant même "
            "que le vent souffle.")

    # lever0 tel que GZ(θs) = lever0 · cos²(θs) : c'est le bras de vent qui
    # amène tout juste le navire à l'angle statique admissible
    gz_s = courbe.gz(theta_s)
    cos2 = math.cos(math.radians(theta_s)) ** 2
    lever0 = gz_s / cos2 if cos2 > 0 else float("nan")

    z = float(vent.get("Z_windage_lateral_m") or 0.0)
    aire_vent = float(vent.get("Windage_area_m2") or 0.0)
    if lever0 != lever0 or lever0 <= 0 or z <= 0 or displacement_t <= 0:
        force_n = float("nan")
        report.messages.append(
            "Force de vent admissible non calculable : bras de redressement "
            f"nul ou négatif à {theta_s:.1f}°, ou bras de vent "
            "(Z_windage_lateral) absent du dossier.")
    else:
        # F·Z = Δ·g·lever0 : le moment du vent qui équilibre le redressement
        force_n = lever0 * (displacement_t * 1000.0) * G / z
    report.add_information(
        "NR500_VOILE_F", "Force de vent admissible à l'angle statique",
        force_n, "N", groupe=groupe)
    # La pression et la vitesse, à la convention du dossier (D-58). Le recueil
    # du bord imprime F, la pression et la vitesse sur ses six cas sous voile ;
    # on y lit F = C · P · A avec C = 1,10 sur les six (coefficient de forme
    # de la silhouette), et P = k · V² avec k = 0,611 = ½·ρ_air (ρ_air =
    # 1,222 kg/m³) sur les six aussi. Les deux nombres sont dans navire.json
    # avec leur source ; sans eux, la pression est F / A tout court et on ne
    # fabrique pas de nœuds.
    c_forme = float(seuils.get("coefficient_force_vent") or 1.0)
    pression = force_n / (c_forme * aire_vent) if aire_vent > 0 else float("nan")
    report.add_information(
        "NR500_VOILE_P",
        "Pression de vent correspondante (F / aire au vent)" if c_forme == 1.0 else
        f"Pression de vent correspondante (F / ({c_forme:.2f} × aire au vent), convention du dossier)",
        pression, "N/m²", groupe=groupe)
    k = seuils.get("pression_par_v2_pa_s2_m2")
    if k and float(k) > 0 and pression == pression and pression >= 0:
        v_ms = math.sqrt(pression / float(k))
        report.add_information(
            "NR500_VOILE_V", "Vitesse de vent correspondante (vent travers constant)",
            v_ms * 1.943844, "nœuds", groupe=groupe)
    else:
        report.messages.append(
            "Vitesse de vent non affichée : le dossier ne donne pas la "
            "relation pression/vitesse (« pression_par_v2_pa_s2_m2 » dans les "
            "critères du navire).")

    # ------------------------------------------------ angle statique / pont
    if plafond_pont is None:
        report.add("NR500_VOILE_ANG",
                   "Angle statique sous vent ≤ 90 % de l'angle d'immersion "
                   "du pont", float("nan"), float("nan"), "<=", "deg",
                   groupe=groupe)
        report.messages.append(
            "Angle d'immersion du pont inconnu : le dossier ne donne ni le "
            "creux sur quille ni la largeur hors membres. Seule la borne des "
            f"{theta_max:.0f}° a été appliquée à l'angle statique.")
    else:
        # seuil arrondi au centième de degré : il DÉRIVE d'un angle estimé au
        # demi-degré près, l'écrire à quinze décimales lui donnerait une
        # précision qu'il n'a pas
        report.add("NR500_VOILE_ANG",
                   f"Angle statique sous vent ≤ {fraction * 100:.0f} % de "
                   f"l'angle d'immersion du pont ({angle_pont_deg:.1f}°, "
                   f"{'estimé' if estime else 'du dossier'})",
                   round(theta_s, 2), round(plafond_pont, 2), "<=", "deg",
                   groupe=groupe)
    if estime:
        report.messages.append(
            f"Angle d'immersion du pont estimé à {angle_pont_deg:.1f}° depuis "
            "le creux et la largeur, sans tonture ni bouge : l'angle statique "
            f"admissible ({theta_s:.1f}°) est gouverné par {gouverne}.")
    elif plafond_pont is not None:
        report.messages.append(
            f"Angle d'immersion du pont : {angle_pont_deg:.1f}°, tel que le "
            f"dossier l'imprime ({fraction * 100:.0f} % = {plafond_pont:.1f}°) : "
            f"l'angle statique admissible ({theta_s:.1f}°) est gouverné par "
            f"{gouverne}.")

    # ------------------------------------------------ aire GZ / bras de vent
    seuil_aire = seuils.get("aire_gz_vent_m_rad_min", 0.065)
    aire, motif = _aire_gz_moins_vent(courbe, lever0, theta_s, theta_f_deg)
    if motif:
        report.messages.append(motif)
    report.add("NR500_VOILE_AIRE",
               f"Aire entre GZ et le bras de vent, de {theta_s:.1f}° à "
               "l'angle d'envahissement θf"
               + ("" if theta_f_deg is None else f" ({theta_f_deg:.1f}°)"),
               aire, seuil_aire, ">=", "m.rad", groupe=groupe)
    return report


def _aire_gz_moins_vent(courbe, lever0, theta_s, theta_f_deg, n=400):
    """Aire entre la courbe GZ et le bras de vent `lever0·cos²θ`, de l'angle
    statique à l'angle d'envahissement (m·rad), et le motif qui empêche de la
    mesurer le cas échéant.

    Les angles sont comptés depuis la VERTICALE (`weather._CourbeCote` lit la
    courbe résiduelle du côté où le navire gîte) : c'est indispensable, puisque
    le bras de vent est en cos²θ et qu'un cosinus compté depuis autre chose que
    la verticale ne veut rien dire.

    On ne prolonge jamais la courbe : au-delà du dernier angle tabulé des
    pantocarènes, l'aire n'est pas mesurable et on le dit."""
    if lever0 != lever0:
        return float("nan"), None      # motif déjà dit par l'appelant
    if theta_f_deg is None:
        return float("nan"), (
            "Aire entre GZ et le bras de vent non évaluable : angle "
            "d'envahissement θf inconnu (aucun point d'envahissement au "
            "dossier).")
    if theta_f_deg <= theta_s:
        return float("nan"), (
            f"Aire entre GZ et le bras de vent non évaluable : l'angle "
            f"d'envahissement ({theta_f_deg:.1f}°) est déjà atteint à l'angle "
            f"statique sous vent ({theta_s:.1f}°) — le pont plonge avant que "
            "le navire ne se redresse.")
    if theta_f_deg > courbe.sous_le_vent_max + 1e-9:
        return float("nan"), (
            f"Aire entre GZ et le bras de vent non évaluable : la courbe GZ "
            f"s'arrête à {courbe.sous_le_vent_max:.1f}°, avant l'angle "
            f"d'envahissement ({theta_f_deg:.1f}°). Il faudrait prolonger les "
            "pantocarènes, ce qui inventerait l'aire.")
    if n % 2:
        n += 1
    xs = np.linspace(theta_s, theta_f_deg, n + 1)
    ys = np.array([courbe.gz(float(x))
                   - lever0 * math.cos(math.radians(float(x))) ** 2
                   for x in xs])
    h = math.radians(xs[1] - xs[0])
    aire = ys[0] + ys[-1] + 4 * sum(ys[1:-1:2]) + 2 * sum(ys[2:-1:2])
    return float(aire * h / 3), None


def rapport_critere_meteo(navire, wres, groupe="", critere=None):
    """Le critère météo IS2008 §2.3 mis en lignes de tableau.

    `weather.evaluate` rend un résultat détaillé (angles, bras, aires) fait
    pour être lu et tracé ; l'écran et le rapport, eux, veulent des lignes
    « valeur / seuil / verdict » comme les autres critères. C'est la seule
    chose que fait cette fonction — aucun calcul, aucun seuil de plus."""
    if critere is None:
        critere = navire.criteres.get("critere_meteo", {})
    report = CriteriaReport()
    if wres is None:
        return report
    if getattr(wres, "chavire", False):
        # le bras de vent établi n'est jamais rattrapé : le pire résultat,
        # dit comme un échec chiffré, pas comme un calcul qui n'a pas abouti
        report.add("METEO_TIENT", "GZ maximal ≥ bras de vent établi lw1",
                   float(wres.details.get("gz_max_m", float("nan"))), wres.lw1_m,
                   ">=", "m", groupe=groupe)
        report.messages.extend(wres.messages)
        return report
    if not wres.evaluable:
        report.add("METEO_THETA0", "Gîte sous vent établi θ0", float("nan"),
                   critere.get("angle_gite_vent_stable_deg_max", 16.0), "<=",
                   "deg", groupe=groupe)
        report.messages.extend(wres.messages)
        return report
    limite = float(getattr(wres, "limite_theta0_deg", None)
                   or critere.get("angle_gite_vent_stable_deg_max", 16.0))
    report.add("METEO_THETA0", "Gîte sous vent établi θ0", wres.theta0_deg,
               round(limite, 2), "<=", "deg", groupe=groupe)
    report.add("METEO_AIRE", "Aire b (redressement) ≥ aire a (chavirement)",
               wres.area_b, wres.area_a, ">=", "m.rad", groupe=groupe)
    # tout ce qu'il faut pour REFAIRE le calcul à la main (RS, D-78) : le
    # recueil imprime ces grandeurs, le rapport les imprime aussi
    d = wres.details or {}
    for code, libelle, valeur, unite in (
            ("METEO_P", "Pression du vent P (selon h)",
             d.get("p_pa") if d.get("h_vent_m") is not None else None, "N/m²"),
            ("METEO_LW1", "Bras de vent établi lw1", wres.lw1_m, "m"),
            ("METEO_LW2", "Bras de rafale lw2 = 1,5 lw1", wres.lw2_m, "m"),
            ("METEO_AIRE_A", "Aire a (chavirement)", wres.area_a, "m.rad"),
            ("METEO_THETA1", "Angle de roulis au vent θ1", wres.theta1_deg, "deg"),
            ("METEO_THETA2", "Borne de l'aire b θ2 (50°, θc ou θf)", wres.theta2_deg, "deg"),
            ("METEO_T", "Période de roulis T", wres.roll_period_s, "s"),
            ("METEO_Z", "Bras du vent Z", d.get("z_m"), "m"),
            ("METEO_R", "Facteur r", d.get("r"), ""),
            ("METEO_X1", "Facteur X1 (B/d)", d.get("x1"), ""),
            ("METEO_X2", "Facteur X2 (Cb)", d.get("x2"), ""),
            ("METEO_K", "Facteur k (quilles anti-roulis)", d.get("k"), ""),
            ("METEO_S", "Facteur s (période)", d.get("s"), "")):
        if valeur is None:
            continue
        report.add_information(code, libelle, float(valeur), unite, groupe=groupe)
    report.messages.extend(wres.messages)
    return report


# ---------------------------------------------------------------- présentation
# Le nombre de décimales dépend de l'UNITÉ, pas de la ligne : une aire se lit
# au dix-millième (les seuils sont 0,055 / 0,090 / 0,030), un bras au
# millimètre, un angle au centième de degré, une force au newton. Écrire tout
# à trois décimales — et les informations à une seule — faisait lire « 0.3 m »
# pour un bras de vent de 0,260 m, ou « 0.055 ≥ 0.055 NON CONFORME » (RS-5,
# D-78). Une seule fonction pour l'écran et le rapport.
DECIMALES_PAR_UNITE = {"m.rad": 4, "m·rad": 4, "m": 3, "deg": 2, "°": 2,
                       "t": 1, "t·m": 1, "t.m": 1, "N": 0, "N/m²": 1,
                       "nœuds": 1, "s": 2, "": 3}


def format_nombre(valeur, unite=""):
    """`valeur` écrite avec les décimales de son unité (voir
    `DECIMALES_PAR_UNITE`), espaces pour les milliers."""
    try:
        v = float(valeur)
    except (TypeError, ValueError):
        return "—"
    if v != v:
        return "—"
    if v in (float("inf"), float("-inf")):
        return "∞" if v > 0 else "−∞"
    nd = DECIMALES_PAR_UNITE.get(unite, 3)
    return f"{v:,.{nd}f}".replace(",", " ")


def evaluate_ligne_de_charge(navire, eq, groupe="Ligne de charge"):
    """Le tirant d'eau face à la marque d'été (R-1, D-78).

    Le premier chiffre d'un plan de chargement, que Carène ne contrôlait pas.
    Le tirant d'eau d'été vient du certificat de franc-bord
    (`dimensions.tirant_eau_ete_m` dans navire.json, à renseigner dans
    « Créer ou modifier le navire… ») ; il se compare au tirant d'eau MILIEU de
    l'équilibre, lu dans la même table que lui — donc en eau de mer : un navire
    en eau douce s'enfonce, mais sa ligne de charge d'eau douce monte d'autant
    (FWA), et la comparaison en eau de mer reste la bonne. Sans valeur au
    dossier, rien n'est contrôlé et un message le dit : on n'invente pas une
    marque.

    Rend un CriteriaReport (vide de lignes si la marque n'est pas connue)."""
    report = CriteriaReport()
    dims = (getattr(navire, "manifest", None) or {}).get("dimensions", {})
    brut = dims.get("tirant_eau_ete_m")
    try:
        t_ete = float(brut) if brut not in (None, "") else None
    except (TypeError, ValueError):
        t_ete = None
    if not t_ete or t_ete <= 0:
        report.messages.append(
            "Ligne de charge non contrôlée : le dossier ne donne pas le tirant "
            "d'eau d'été (certificat de franc-bord). Renseignez-le dans « Créer "
            "ou modifier le navire… › Identification et dimensions ».")
        return report
    report.add("LIGNE_CHARGE", "Tirant d'eau milieu ≤ tirant d'eau d'été",
               round(float(eq.draft_m), 3), round(t_ete, 3), "<=", "m", groupe=groupe)
    return report
