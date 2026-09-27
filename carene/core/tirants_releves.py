# -*- coding: utf-8 -*-
"""Le relevé de tirants d'eau du bord, confronté au calcul (D-60).

Le bord (22/09/2026) : « une correction par tirant d'eau automatique ? Je
marque mes tirants d'eau réels, et ça corrige d'un point *fictif* et me
prévient de combien il est et où il est positionné (et s'il a une valeur
étrange). »

C'est le contrôle que fait tout officier au départ d'escale : le chargement
sur le papier dit un déplacement et un centre ; la coque, elle, dit ce qu'elle
dit. L'écart entre les deux est un **poids qu'on n'a pas compté** — une
citerne qu'on croyait vide, des colis embarqués sans manifeste, de l'eau dans
une cale —, et deux nombres le décrivent entièrement : **combien**, et **où**.

Ce module ne fait que cela, et sans rien inventer :

1. **ramener les lectures aux perpendiculaires.** Les repères sont peints là
   où on les voit, pas aux perpendiculaires (sur le navire de référence, 1,75 m et 61,20 m
   du couple 0 contre −0,25 m et 64,476 m) : confondre les deux surestime la
   pente d'assiette de 9 %. La flottaison est une droite, on l'y prolonge ;
2. **lire la table** à l'assiette et au tirant d'eau milieu ainsi obtenus :
   déplacement et LCB, tels que le dossier les tabule. Pas de correction de
   première et de seconde assiette à faire ici — la table de Carène est à
   DEUX entrées (assiette, tirant d'eau), l'assiette y est déjà dedans ;
3. **corriger de la densité** de l'eau du port, si elle est donnée, par le
   rapport à celle des tables ;
4. **comparer** au chargement calculé, et rendre le poids fictif : sa masse
   `Δ_observé − Δ_calculé`, et sa position `x` telle que les moments
   concordent.

**Ce qu'un tirant d'eau ne dit pas, ce module ne le dit pas non plus.** Des
tirants d'eau donnent une masse et une abscisse : jamais une hauteur (le KG
ne se lit pas sur la coque, il se mesure à l'expérience de stabilité), et la
position transversale seulement si l'on relève les deux bords. Le poids fictif
est donc rendu sans VCG ni TCG : c'est l'appelant qui le pose au centre de
gravité courant du navire, de sorte qu'il change le déplacement et l'assiette
— ce que les tirants d'eau mesurent — et rien d'autre.

Et quand l'écart n'a pas de sens physique, on le dit plutôt que de l'écrire
joliment : une position hors du navire, une masse énorme, un moment sans
masse, une lecture hors des tables, une densité improbable, une tonture
marquée — chacune a son alerte, en toutes lettres.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .stability import abscisses_tirants_eau

# Densité des tables hydrostatiques quand le dossier ne la déclare pas : l'eau
# de mer normalisée. C'est la valeur de tous les recueils consultés (celui
# du navire de référence imprime « Water Density 1.0250 » sur chaque condition), mais un
# dossier peut être tabulé en eau douce : quand la clé manque, on applique
# 1,025 ET on le dit (`remarques`).
DENSITE_MER = 1.025

# Le nom sous lequel le poids fictif entre dans les poids divers du point. Il
# est ici, et pas dans la fenêtre, parce que trois endroits le reconnaissent :
# la fenêtre qui le pose, le rapport qui dit s'il est appliqué, et la fenêtre
# encore, qui remplace le précédent au lieu de l'empiler.
NOM_POIDS = "Écart aux tirants d'eau relevés"

# Seuils des alertes. Ce ne sont pas des règlements : ce sont les bornes au-delà
# desquelles un officier regarde son relevé de plus près.
MASSE_NEGLIGEABLE_PC = 0.2        # % du déplacement : en deçà, tout concorde
MASSE_NEGLIGEABLE_T = 1.0         # …et jamais moins d'une tonne
MASSE_FORTE_PC = 5.0              # % du déplacement : écart considérable
TONTURE_NOTABLE_M = 0.05          # flèche au milieu : tonture / contre-tonture
DENSITE_MIN, DENSITE_MAX = 0.995, 1.035
MARGE_HORS_NAVIRE_M = 2.0         # au-delà des perpendiculaires


@dataclass
class Releve:
    """Ce que le bord lit sur la coque, tel qu'il le lit.

    `aux_perpendiculaires` : les valeurs sont déjà ramenées aux PP (relevé
    d'un autre logiciel, ou navire dont les repères sont aux PP) — Carène n'y
    touche alors pas. Sinon elles sont lues **aux repères peints**, et c'est
    ce module qui les ramène.
    """

    te_ar_m: float = 0.0
    te_av_m: float = 0.0
    te_milieu_m: float | None = None      # facultatif : tonture / contre-tonture
    densite_eau: float | None = None      # facultatif : l'eau du port
    aux_perpendiculaires: bool = False
    date: str = ""
    note: str = ""
    # LES DEUX BORDS (3.1, D-80) — facultatif : un seul bord suffit. Relevés,
    # `te_*_m` sont les lectures de BÂBORD et `te_*_td_m` celles de TRIBORD ;
    # le calcul prend la moyenne des deux, qui efface l'effet d'une gîte au
    # moment du relevé. Sans eux, `te_*_m` est la lecture du seul bord relevé.
    te_ar_td_m: float | None = None
    te_av_td_m: float | None = None
    te_milieu_td_m: float | None = None

    @property
    def deux_bords(self):
        return self.te_ar_td_m is not None and self.te_av_td_m is not None

    @staticmethod
    def _moyenne(un, autre):
        return float(un) if autre is None else (float(un) + float(autre)) / 2.0

    @property
    def ar(self):
        """Le tirant d'eau arrière retenu : la moyenne des deux bords, ou le
        seul bord relevé."""
        return self._moyenne(self.te_ar_m, self.te_ar_td_m)

    @property
    def av(self):
        return self._moyenne(self.te_av_m, self.te_av_td_m)

    @property
    def milieu(self):
        if self.te_milieu_m is None:
            return None
        return self._moyenne(self.te_milieu_m, self.te_milieu_td_m)

    def gite_apparente_deg(self, largeur_m):
        """La gîte au moment du relevé, lue sur l'écart tribord − bâbord
        (positive : sur tribord), ou None avec un seul bord."""
        if not self.deux_bords or not largeur_m:
            return None
        ecart = ((self.te_ar_td_m - self.te_ar_m) + (self.te_av_td_m - self.te_av_m)) / 2.0
        return math.degrees(math.atan2(ecart, float(largeur_m)))

    def lecture(self):
        """Le relevé en une ligne, tel que le bord l'a lu."""
        def paire(bd, td):
            return (f"{bd:.3f}" if td is None
                    else f"{bd:.3f} Bd / {td:.3f} Td")
        txt = f"AR {paire(self.te_ar_m, self.te_ar_td_m)} m · AV {paire(self.te_av_m, self.te_av_td_m)} m"
        if self.te_milieu_m is not None:
            txt += f" · milieu {paire(self.te_milieu_m, self.te_milieu_td_m)} m"
        if self.deux_bords:
            txt += f" (moyennes AR {self.ar:.3f} · AV {self.av:.3f})"
        return txt

    def to_dict(self):
        d = {"te_ar_m": float(self.te_ar_m), "te_av_m": float(self.te_av_m),
             "aux_perpendiculaires": bool(self.aux_perpendiculaires)}
        if self.te_milieu_m is not None:
            d["te_milieu_m"] = float(self.te_milieu_m)
        for cle in ("te_ar_td_m", "te_av_td_m", "te_milieu_td_m"):
            v = getattr(self, cle)
            if v is not None:
                d[cle] = float(v)
        if self.densite_eau is not None:
            d["densite_eau"] = float(self.densite_eau)
        if self.date:
            d["date"] = str(self.date)
        if self.note:
            d["note"] = str(self.note)
        return d

    @classmethod
    def from_dict(cls, d):
        d = d or {}

        def opt(cle):
            v = d.get(cle)
            return None if v in (None, "") else float(v)

        return cls(te_ar_m=float(d.get("te_ar_m", 0.0)),
                   te_av_m=float(d.get("te_av_m", 0.0)),
                   te_milieu_m=opt("te_milieu_m"),
                   te_ar_td_m=opt("te_ar_td_m"), te_av_td_m=opt("te_av_td_m"),
                   te_milieu_td_m=opt("te_milieu_td_m"),
                   densite_eau=opt("densite_eau"),
                   aux_perpendiculaires=bool(d.get("aux_perpendiculaires", False)),
                   date=str(d.get("date") or ""), note=str(d.get("note") or ""))


@dataclass
class Ecart:
    """Ce que Carène tire du relevé : le poids fictif, et ce qui l'entoure."""

    # le relevé ramené aux perpendiculaires
    te_ar_pp_m: float = 0.0
    te_av_pp_m: float = 0.0
    te_milieu_pp_m: float = 0.0
    assiette_m: float = 0.0
    ramene_aux_pp: bool = False
    source_abscisses: str = ""            # perpendiculaires / reperes / inconnu
    # ce que la table en dit
    dans_domaine: bool = True
    deplacement_observe_t: float = 0.0
    lcb_observe_m: float = 0.0
    tpc_t_cm: float | None = None
    mct_tm_cm: float | None = None
    densite_tables: float = DENSITE_MER
    densite_eau: float | None = None
    # ce que le chargement calculé dit
    deplacement_calcule_t: float = 0.0
    lcg_calcule_m: float = 0.0
    # le poids fictif
    masse_t: float = 0.0
    moment_tm: float = 0.0
    position_m: float | None = None
    position_fiable: bool = False
    concordent: bool = False
    # informations et alertes
    tonture_m: float | None = None
    alertes: list = field(default_factory=list)
    remarques: list = field(default_factory=list)

    @property
    def masse_pc(self):
        """L'écart en % du déplacement observé — la façon dont on le juge."""
        d = self.deplacement_observe_t
        return 100.0 * self.masse_t / d if d else 0.0

    def resume(self):
        """Une phrase : c'est elle qu'on met au bandeau et au rapport."""
        if self.concordent:
            return ("Les tirants d'eau relevés concordent avec le calcul "
                    f"(écart {self.masse_t:+.1f} t, {self.masse_pc:+.2f} %).")
        if self.position_fiable:
            return (f"Poids fictif : {self.masse_t:+.1f} t "
                    f"({self.masse_pc:+.2f} % du déplacement) à "
                    f"x = {self.position_m:.2f} m.")
        return (f"Écart de moment {self.moment_tm:+.0f} t·m pour une masse de "
                f"{self.masse_t:+.1f} t : la position n'a pas de sens.")


def _abscisses_reperes(navire):
    """(x_arrière, x_milieu|None, x_avant) des repères peints, depuis
    `dimensions.reperes_tirants_eau` (« C2 (1.75 m / C0) »), ou None si le
    dossier ne les donne pas — on ne devine pas où le peintre est passé."""
    dims = (getattr(navire, "manifest", None) or {}).get("dimensions", {})
    reperes = dims.get("reperes_tirants_eau") or {}

    def lire(cle):
        brut = reperes.get(cle)
        if not brut:
            return None
        try:
            return float(str(brut).split("(")[1].split("m")[0].strip())
        except (IndexError, ValueError):
            return None

    x_ar, x_av = lire("arriere"), lire("avant")
    if x_ar is None or x_av is None or abs(x_av - x_ar) < 1e-6:
        return None
    return x_ar, lire("milieu"), x_av


def densite_des_tables(navire):
    """La densité de l'eau des tables hydrostatiques du dossier, et si elle a
    été déclarée. Rend (densité, déclarée)."""
    dims = (getattr(navire, "manifest", None) or {}).get("dimensions", {})
    v = dims.get("densite_eau_tables")
    try:
        v = float(v)
    except (TypeError, ValueError):
        return DENSITE_MER, False
    return (v, True) if v > 0 else (DENSITE_MER, False)


def comparer(navire, releve, deplacement_calcule_t, lcg_calcule_m):
    """Confronte un relevé de tirants d'eau au chargement calculé.

    `deplacement_calcule_t` et `lcg_calcule_m` sont le poids et le centre de
    gravité longitudinal que le point additionne (`condition.totals()`), pas
    ceux de l'équilibre : c'est bien le chargement déclaré que l'on met à
    l'épreuve de la coque.
    """
    ec = Ecart(deplacement_calcule_t=float(deplacement_calcule_t),
               lcg_calcule_m=float(lcg_calcule_m))
    x_ppar, x_ppav, source = abscisses_tirants_eau(navire)
    ec.source_abscisses = source

    # --- 1. ramener les lectures aux perpendiculaires
    # les deux bords s'ils sont relevés (moyenne), le seul relevé sinon
    te_ar, te_av = releve.ar, releve.av
    dims = (getattr(navire, "manifest", None) or {}).get("dimensions", {})
    gite = releve.gite_apparente_deg(dims.get("largeur_hors_membres_m"))
    if gite is not None:
        ec.remarques.append(
            f"Relevé des deux bords : gîte apparente de {abs(gite):.1f}° sur "
            f"{'tribord' if gite > 0 else 'bâbord'} au moment de la lecture — "
            "la moyenne des deux bords l'efface.")
    elif not releve.deux_bords:
        ec.remarques.append(
            "Relevé d'un seul bord : c'est suffisant navire droit. Avec une "
            "gîte, relevez les deux bords — la moyenne en efface l'effet.")
    reperes = _abscisses_reperes(navire)
    if releve.aux_perpendiculaires:
        ec.te_ar_pp_m, ec.te_av_pp_m = te_ar, te_av
        ec.remarques.append("Lectures déclarées déjà ramenées aux "
                            "perpendiculaires : Carène ne les a pas retouchées.")
    elif reperes is None or source != "perpendiculaires":
        ec.te_ar_pp_m, ec.te_av_pp_m = te_ar, te_av
        ec.remarques.append(
            "Le dossier ne donne pas à la fois les repères de tirants d'eau et "
            "les perpendiculaires : les lectures sont prises telles quelles, "
            "comme si les repères étaient aux perpendiculaires. L'assiette, "
            "donc l'écart, s'en trouve approchée.")
    else:
        x_rep_ar, _x_rep_mil, x_rep_av = reperes
        pente = (te_av - te_ar) / (x_rep_av - x_rep_ar)
        ec.te_ar_pp_m = te_ar + (x_ppar - x_rep_ar) * pente
        ec.te_av_pp_m = te_ar + (x_ppav - x_rep_ar) * pente
        ec.ramene_aux_pp = True
    ec.assiette_m = ec.te_ar_pp_m - ec.te_av_pp_m
    ec.te_milieu_pp_m = (ec.te_ar_pp_m + ec.te_av_pp_m) / 2.0

    # la tonture / contre-tonture : le milieu relevé contre la droite des deux
    # bouts. La table est à deux entrées (assiette, tirant d'eau) et ne sait
    # pas ce qu'est une coque arquée : on mesure la flèche, on la dit, on ne
    # la corrige pas.
    if releve.milieu is not None:
        if reperes is not None and reperes[1] is not None and not releve.aux_perpendiculaires:
            x_rep_ar, x_rep_mil, x_rep_av = reperes
            droite = te_ar + (x_rep_mil - x_rep_ar) * (te_av - te_ar) / (x_rep_av - x_rep_ar)
        else:
            droite = (te_ar + te_av) / 2.0
        ec.tonture_m = float(releve.milieu) - droite

    # --- 2. la table, à cette assiette et à ce tirant d'eau
    hydro = getattr(navire, "hydro", None)
    if hydro is None:
        ec.alertes.append("Ce navire n'a pas de table hydrostatique : "
                          "un relevé de tirants d'eau ne peut pas être exploité.")
        return ec
    ec.dans_domaine = bool(hydro.contains(ec.assiette_m, ec.te_milieu_pp_m))
    ligne = navire.hydro_at(ec.assiette_m, ec.te_milieu_pp_m)
    depl = float(ligne.get("Deplacement_t", 0.0))
    ec.lcb_observe_m = float(ligne.get("LCB_m", 0.0))
    for cle, attr in (("TPC_t_cm", "tpc_t_cm"), ("MCT_tm_cm", "mct_tm_cm")):
        if cle in ligne:
            setattr(ec, attr, float(ligne[cle]))

    # --- 3. la densité de l'eau du port
    ec.densite_tables, declaree = densite_des_tables(navire)
    if not declaree:
        ec.remarques.append(
            f"Densité des tables non déclarée au dossier : {DENSITE_MER:g} "
            "(eau de mer) retenue. Renseignez-la dans « Créer ou modifier le "
            "navire… › Identification et dimensions » si votre dossier est "
            "tabulé autrement.")
    ec.densite_eau = None if releve.densite_eau is None else float(releve.densite_eau)
    if ec.densite_eau:
        depl *= ec.densite_eau / ec.densite_tables
    ec.deplacement_observe_t = depl

    # --- 4. le poids fictif : combien, et où
    ec.masse_t = depl - ec.deplacement_calcule_t
    ec.moment_tm = depl * ec.lcb_observe_m - ec.deplacement_calcule_t * ec.lcg_calcule_m
    seuil_masse = max(MASSE_NEGLIGEABLE_T, MASSE_NEGLIGEABLE_PC / 100.0 * depl)
    if abs(ec.masse_t) > seuil_masse:
        ec.position_m = ec.moment_tm / ec.masse_t
        ec.position_fiable = True
    # « concordent » : la masse ET le moment sont négligeables. Un moment seul
    # ne se rattrape pas par un poids — c'est une répartition à revoir.
    seuil_moment = seuil_masse * max(1.0, abs(x_ppav - x_ppar)) / 2.0
    ec.concordent = (abs(ec.masse_t) <= seuil_masse
                     and abs(ec.moment_tm) <= seuil_moment)

    _alerter(ec, x_ppar, x_ppav, seuil_masse)
    return ec


def _alerter(ec, x_ppar, x_ppav, seuil_masse):
    """Les « valeurs étranges » : ce qu'un officier regarderait deux fois.

    Deux familles, et elles ne se commandent pas l'une l'autre. Ce qui touche
    au RELEVÉ — hors table, densité improbable, flèche au milieu, dossier sans
    perpendiculaires — est dit même quand le relevé et le calcul concordent :
    un relevé douteux qui tombe juste reste un relevé douteux. Ce qui touche
    au POIDS FICTIF — position hors du navire, moment sans masse, écart
    considérable — n'a de sens que s'il y a un écart.
    """
    # --- ce qui touche au relevé lui-même
    if not ec.dans_domaine:
        ec.alertes.append(
            f"Tirant d'eau {ec.te_milieu_pp_m:.3f} m à {ec.assiette_m:+.3f} m "
            "d'assiette : hors du domaine des tables hydrostatiques. Le "
            "déplacement observé est extrapolé — sans valeur, et l'écart avec.")
    if ec.densite_eau and not (DENSITE_MIN <= ec.densite_eau <= DENSITE_MAX):
        ec.alertes.append(
            f"Densité de l'eau relevée à {ec.densite_eau:.4f} : hors de "
            f"[{DENSITE_MIN:g} ; {DENSITE_MAX:g}]. Une densité fausse déplace "
            "tout le résultat — vérifiez le densimètre.")
    if ec.tonture_m is not None and abs(ec.tonture_m) >= TONTURE_NOTABLE_M:
        sens = "contre-tonture (le milieu s'enfonce)" if ec.tonture_m > 0 \
            else "tonture (le milieu se relève)"
        ec.alertes.append(
            f"Flèche au milieu de {ec.tonture_m * 100:+.0f} cm — {sens}. Les "
            "tables sont à deux entrées (assiette, tirant d'eau) et ne la "
            "corrigent pas : le déplacement observé s'en écarte d'autant.")
    if ec.source_abscisses != "perpendiculaires":
        ec.alertes.append(
            "Les perpendiculaires ne sont pas renseignées au dossier : "
            "l'assiette est prise sur les repères, et l'écart est approché.")

    # --- ce qui touche au poids fictif : seulement s'il y a un écart
    if ec.concordent:
        return
    if not ec.position_fiable:
        ec.alertes.append(
            f"Masse manquante quasi nulle ({ec.masse_t:+.1f} t) mais moment de "
            f"{ec.moment_tm:+.0f} t·m : ce n'est pas un poids oublié, c'est un "
            "poids mal placé. Cherchez une erreur de position, pas de pesée — "
            "aucune position ne peut être calculée pour un poids nul.")
    elif not (x_ppar - MARGE_HORS_NAVIRE_M <= ec.position_m
              <= x_ppav + MARGE_HORS_NAVIRE_M):
        ec.alertes.append(
            f"Le poids fictif tombe à x = {ec.position_m:.1f} m, hors du navire "
            f"(perpendiculaires {x_ppar:.2f} à {x_ppav:.2f} m) : l'écart ne "
            "s'explique pas par un poids oublié. Vérifiez d'abord les lectures "
            "de tirants d'eau, puis les poids déclarés aux extrémités.")
    if abs(ec.masse_pc) >= MASSE_FORTE_PC:
        ec.alertes.append(
            f"L'écart vaut {ec.masse_pc:+.1f} % du déplacement : c'est "
            "considérable. Une citerne oubliée, une densité fausse ou une "
            "lecture d'un mètre expliquent seules un tel chiffre.")
