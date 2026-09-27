# -*- coding: utf-8 -*-
"""Solveur de chargement : un premier jet, à ajuster ensuite à la main.

Ce qu'il fait, et ce qu'il ne fait pas
--------------------------------------
Il propose une répartition des charges du manifeste dans les cales, puis un
calepinage de chaque cale. C'est une **heuristique**, pas un optimum
démontré : elle donne à l'officier de chargement une base de travail
cohérente et vérifiée, qu'il reprend ensuite librement.

Le calepinage cherche VRAIMENT à occuper la place
-------------------------------------------------
Il ne range plus tous les colis dans un sens pour essayer ensuite d'en
glisser quelques-uns en travers. Pour chaque cale et chaque gabarit, il
compose une trentaine de calepinages complets — en travées le long de X puis
de Y, servies depuis l'arrière, depuis l'avant ou depuis le milieu, depuis
tribord, depuis bâbord ou depuis l'axe, avec l'une ou l'autre orientation
comme orientation préférée, à profondeur de travée choisie ou fixe ; en
blocs réguliers dans le plus grand rectangle libre ; et au plus près du bord,
colis par colis — puis il garde le meilleur. La rotation d'un colis est donc
une **décision** du calepinage, prise avant de poser, et non un rattrapage.

Un calepinage est une liste d'emplacements ORDONNÉE, et cet ordre compte
autant que la liste : réordonner les mêmes emplacements ne change ni le
nombre de colis logés ni la surface occupée, mais il change TOUT pour un lot
qui ne remplit pas la cale — c'est lui qui décide de quel bord, ou de quel
bout, tombe la demi-cale chargée, donc du barycentre du chargement. C'est
l'objet du réglage `disposition` (voir `Reglages`).

Le meilleur, c'est le plus grand nombre de colis logés, puis la plus grande
surface occupée, puis le barycentre le plus proche de celui qu'on vise, puis
— pour que deux exécutions donnent exactement le même plan — le plus faible
étalement et le rang de la stratégie.
Quand le lot ne suffit pas à remplir la cale, on regarde en plus ce que le
calepinage LAISSE au lot suivant : c'est ce qui évite d'étaler cent palettes
dans toute la cale et de n'avoir plus de place pour les suivantes.

Quand un calepinage est épuisé, un **glanage** le recompose sur ce qui reste
réellement libre : c'est là que rentrent les derniers colis, ceux qu'un
calepineur d'un seul jet abandonne.

Pour tenir en quelques secondes sur les mille cinq cents colis d'un
chargement complet, chaque cale est rangée une fois pour toutes dans une
grille de cellules libres ou non (`_Grille`) : « ce rectangle tient-il ? »
devient alors une comparaison au lieu d'un parcours du contour. La position
finalement retenue est toujours revérifiée sur le contour exact.

Les réglages, en trois familles (`Reglages`)
--------------------------------------------
Le bord ne règle pas une liste de cases : il dit *ce qu'il cherche*, *ce
qu'il s'autorise* et *ce qu'il respecte*. La fenêtre du répartiteur porte les
mêmes trois titres, dans le même ordre.

**A · Ce qu'on cherche.** La PRIORITÉ (`objectif`) : ``CAPACITE`` — charger
au maximum, l'assiette suit ; on sert la cale la plus libre, en fraction de
sa surface pour que la petite cave soit servie aussi. ``ASSIETTE_GM`` — tenir
l'assiette visée, quitte à charger moins : le solveur calcule le LCG que la
cargaison doit avoir pour que le navire tombe sur l'assiette demandée, puis
répartit pour l'approcher, en descendant les plus lourdes.

Deux buts, cochés séparément et indépendants l'un de l'autre :
`viser_assiette` (+ `assiette_cible_m`) et `equilibrer_tcg` (+ `tcg_cible_m`).
DÉCOCHER `viser_assiette`, c'est retirer l'assiette de TOUT départage, même
en objectif capacité, où elle départageait les cales également libres (D-34) :
le bord qui dit « remplis, je m'occuperai de l'assiette au ballast » doit être
pris au mot. La GÎTE reste le QUATRIÈME critère — après la capacité et
l'assiette, jamais devant elles (D-38) : deux cales symétriques ont le même
LCG et la même surface, c'est le TCG qui dit laquelle redresse le navire, et
le calepineur préfère, à nombre de colis et surface égaux, la disposition dont
le barycentre transversal tombe le plus près de la cible. Ce qu'on annonce est
un TCG (`Rapport.tcg_prevu_m`), jamais une gîte en degrés : le solveur n'a pas
le GM sous la main, et la gîte réelle se lit au bandeau une fois le plan
appliqué.

**B · Ce qu'on s'autorise.** `empiler` — poser plusieurs couches quand le lot
le permet ; décochée, une seule couche, quoi que dise le stack du lot (le
manifeste n'est pas retouché : c'est `niveaux_possibles` qui plafonne).
`disposition` — DANS QUEL SENS LA CALE SE REMPLIT, et non dans quel sens sont
posés les colis : `TRANSVERSALE`, les colis se disposent d'une muraille à
l'autre (depuis tribord, depuis bâbord ou depuis l'axe, c'est la GÎTE visée
qui décide du côté de départ) ; `LONGITUDINALE`, d'arrière en avant, d'avant
en arrière ou depuis le milieu, et c'est l'ASSIETTE visée qui décide du bout
de départ ; `AUTO`, le calepineur prend ce qui loge le plus.
`rotation_permise` — le droit de tourner un colis de 90°, seul réglage qui
touche encore au sens des colis (avec le catalogue, qui peut déclarer un type
« sans rotation »). `melanger_lots` — décochée, le solveur sert un lot à la
fois : il finit un lot dans une cale avant d'y en commencer un autre, et
n'ouvre une deuxième cale que si la première est pleine ; on remplit moins,
et le rapport dit de combien. `respecter_cale_imposee` — la colonne du
manifeste fait loi.

**C · Ce qu'on respecte.** `respecter_escales` — on n'empile rien sur ce qui
se débarque avant ; l'ordre des escales vient du dehors (`ordre_escales`), et
le réglage ne modélise QUE l'empilement, jamais l'accès (voir `resoudre` et
D-41). `priorite_verticale` — `BAS` (meilleur GM) ou `HAUT` (débarquement
plus facile) : un DÉPARTAGE, au même rang que la gîte, qui ne fait jamais
perdre un colis.

Contraintes toujours respectées :

- **débord du lot** : le calepineur fait tenir l'ENCOMBREMENT (l'emprise plus
  ce qui dépasse de la palette de chaque côté), pas la palette nue — deux lots
  dont les sacs se toucheraient ne tiennent pas côte à côte (D-39). Le
  **jeu d'arrimage** (`Reglages.jeu_m`) s'y ajoute : c'est un DÉBORDEMENT de
  plus, réglé par le bord et commun à tous les colis — deux voisins sont
  séparés de deux jeux, un colis et la muraille d'un seul (D-64) ;
- **charges épinglées** : jamais déplacées, le reste se compose autour ;
- **hauteur libre** : l'empilement ne dépasse pas la hauteur utile de la cale,
  ni celle — plus basse — des zones de hauteur réduite là où le colis est posé ;
- **charge de pont admissible** (t/m²) : ni en moyenne sur la cale, ni sous une
  charge donnée ;
- **stack** (empilement, ex-« gerbage ») : on n'empile jamais au-delà de ce que
  la marchandise supporte,
  et seulement des colis d'un même lot.

Aucune règle de ségrégation IMDG n'est appliquée.

Le module ne dépend pas de Qt. Il ne dépend du moteur hydrostatique que pour
la recherche du LCG cible, et seulement si cet objectif est demandé. Il
emploie numpy pour la grille de calepinage, comme le reste de `core`.
"""
from __future__ import annotations

import bisect
import math
import re
from dataclasses import dataclass, field

from .cargo_model import Placement, mention_debord

ASSIETTE_GM = "assiette_gm"
# En objectif CAPACITÉ, poids du départage par l'assiette face au
# remplissage (fraction de surface libre, entre 0 et 1) : voir `score_cale`.
POIDS_ASSIETTE_CAPACITE = 6.0
# En objectif CAPACITÉ, poids de la PRIORITÉ VERTICALE face au remplissage.
# 0,5 se lit : on descend (ou on monte) les charges tant que ça ne coûte pas
# la moitié du remplissage d'une cale. Sans ce terme, le réglage serait
# muet en capacité — la fraction de surface libre change à chaque colis,
# deux cales superposées ne sont donc jamais à égalité stricte et le
# départage de `score_cale` ne serait jamais lu. Le bord aurait une case qui
# ne commande rien, ce qui est pire qu'une case absente.
POIDS_VERTICAL_CAPACITE = 0.5
CAPACITE = "capacite"

# DISPOSITION demandée au calepineur (`Reglages.disposition`) : dans quel sens
# la cale se REMPLIT, c'est-à-dire dans quel ordre les emplacements sont
# servis. Ce n'est pas le sens des colis — ça, c'est `rotation_permise` et le
# catalogue. Le bord l'a dit ainsi : « transversal signifie que les colis sont
# disposés de tribord à bâbord (ou de bâbord à tribord) pour satisfaire la
# gîte souhaitée, quand longitudinal agit sur le trim (l'assiette) ».
#
# C'est l'ordre de service qui décide où tombe un lot qui ne remplit pas la
# cale, donc du barycentre du chargement : en TRANSVERSALE, le barycentre
# transversal (la gîte) ; en LONGITUDINALE, le barycentre longitudinal
# (l'assiette). « auto » laisse le calepineur prendre ce qui loge le plus,
# comme il l'a toujours fait.
AUTO = "auto"
LONGITUDINALE = "longitudinale"     # la cale se remplit d'un bout à l'autre (X)
TRANSVERSALE = "transversale"       # la cale se remplit d'une muraille à l'autre (Y)

# Priorité verticale (`Reglages.priorite_verticale`) : où servir d'abord, à
# capacité et assiette équivalentes. « bas » descend les charges (meilleur
# GM), « haut » les monte (débarquement plus facile, moins de manutention en
# cale) ; `AUTO` laisse le solveur faire comme il l'a toujours fait. C'est un
# DÉPARTAGE et non une contrainte : à aucun moment il ne refuse un colis.
BAS = "bas"
HAUT = "haut"

# ÉCART d'usine entre deux colis : la marge de calepinage sous laquelle deux
# emprises ne descendent jamais — deux charges ne se touchent pas exactement.
# C'est un ÉCART TOTAL, mesuré une fois entre deux voisins : c'est en ces
# termes que raisonne le calepineur, qui en laisse la moitié de part et
# d'autre de chaque colis.
JEU_M = 0.02
# Le même, vu comme le bord le règle : un DÉBORDEMENT par colis, de chaque
# côté (D-64) — donc la moitié de l'écart. C'est la valeur que prend
# `Reglages.jeu_m`, et celle que la molette de la vue Chargement affiche. À ne
# pas confondre avec le DÉBORD, qui est une dimension du lot, se règle au
# manifeste et s'ajoute à celui-ci (D-39).
DEBORD_JEU_M = JEU_M / 2


def _rect_pris(p):
    """La place que ce colis prend au sol : son encombrement (débord compris).

    SANS le jeu d'arrimage : à l'intérieur du calepineur, le jeu n'est pas
    porté par les rectangles mais par l'occupation (`_Occupation.jeu`, moitié
    de part et d'autre). Le reste de l'application, qui juge une pose faite à
    la main, passe lui par `cargo_model.rect_occupe(colis, jeu)` (D-64).

    Passe par `getattr` parce que le calepineur reçoit aussi des obstacles qui
    ne sont pas des `Placement` — une zone interdite n'a pas de débord."""
    r = getattr(p, "rect_encombrement", None)
    return r if r is not None else p.rect

# Une zone de la cale annonce sa hauteur libre dans son nom (« hauteur libre
# 1.70 m ») : c'est ainsi que le plan des cales est décalqué. Rien de deviné :
# sans nombre suivi de « m », la zone est un mur, pas un plafond bas.
_RE_HAUTEUR = re.compile(r"([\d.,]+)\s*m")


# Marque portée par un obstacle qui vient d'une ÉPONTILLE AMOVIBLE mise en
# place. Une épontille n'est pas de la structure : elle se pose et se dépose
# à chaque escale (manuel d'assujettissement, § *Removable
# pillars*, MSL 50 kN). Quand elle est en place, c'est un MUR — au même titre
# que le contour de la cale — quel que soit son nom : la marque évite qu'une
# épontille nommée « épontille d'entrepont 2 m » soit lue comme un plafond bas.
MARQUE_EPONTILLE = "epontille"


def est_epontille(obstacle) -> bool:
    """Cette zone interdite vient-elle d'une épontille mise en place ?"""
    return len(obstacle) > 5 and obstacle[5] == MARQUE_EPONTILLE


def rect_epontille(epontille):
    """L'emprise (x0, y0, x1, y1, nom, marque) d'une épontille.

    `x` et `y` sont le CENTRE de l'épontille — c'est le point qu'on clique
    dans l'éditeur de plans ; `longueur_m` court selon X, `largeur_m` selon Y
    (repère navire, Y positif bâbord)."""
    x = float(epontille.get("x", 0.0))
    y = float(epontille.get("y", 0.0))
    lx = abs(float(epontille.get("longueur_m", 0.0))) / 2.0
    ly = abs(float(epontille.get("largeur_m", 0.0))) / 2.0
    nom = str(epontille.get("nom") or "épontille")
    return (x - lx, y - ly, x + lx, y + ly, nom, MARQUE_EPONTILLE)


def hauteur_libre_de(obstacle):
    """Hauteur libre (m) annoncée par une zone de cale, 0 si elle n'en dit rien.

    Une zone SANS hauteur est interdite (épontille, descente, puits) : rien
    ne s'y pose. Une zone AVEC hauteur est un calque, au même titre que les
    charges admissibles (D-12) : on y pose, mais une pile plus haute que la
    hauteur annoncée est signalée en rouge, et le solveur ne l'y met pas."""
    if est_epontille(obstacle):
        # une épontille en place tient du plancher au barrot : elle ne se lit
        # jamais comme un plafond bas, même si son nom porte un nombre de
        # mètres — rien ne se pose dessus
        return 0.0
    if len(obstacle) <= 4 or not obstacle[4]:
        return 0.0
    m = _RE_HAUTEUR.search(str(obstacle[4]))
    if not m:
        return 0.0
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return 0.0


def _rects_se_chevauchent(rect, o, tol=1e-9):
    """Surface commune entre une emprise et un rectangle (x0, y0, x1, y1[, nom])
    dont les coins peuvent être donnés dans n'importe quel ordre."""
    x0, y0, x1, y1 = rect
    ox0, oy0, ox1, oy1 = (float(v) for v in o[:4])
    return (x0 < max(ox0, ox1) - tol and min(ox0, ox1) < x1 - tol
            and y0 < max(oy0, oy1) - tol and min(oy0, oy1) < y1 - tol)


def classes_imdg_de(texte):
    """« 3, 9 » → ["3", "9"] ; « toutes » → ["toutes"] ; « » → []."""
    out = []
    for morceau in str(texte or "").replace(";", ",").replace(" ", ",").split(","):
        m = morceau.strip()
        if m:
            out.append("toutes" if m.lower() in ("toutes", "tous", "*") else m)
    return out


def imdg_admis(classes_admises, classe):
    """Une marchandise de cette classe IMDG peut-elle aller là ? (D-83)

    Pas de classe (marchandise ordinaire) : partout. Sinon, seulement là où
    la cale admet « toutes » les classes, la classe elle-même (« 2.1 »), ou sa
    classe principale (« 2 » admet 2.1, 2.2, 2.3)."""
    classe = str(classe or "").strip().upper()
    if not classe:
        return True
    admises = [str(c).strip().upper() for c in (classes_admises or [])]
    if "TOUTES" in admises:
        return True
    # « 1.4S » : la division 1.4, groupe de compatibilité S — admise là où
    # l'on admet 1.4S, 1.4 ou la classe 1 (3.4.0)
    division = classe.rstrip("ABCDEFGHIJKLNS") if classe[:1] == "1" else classe
    return (classe in admises or division in admises
            or classe.split(".")[0] in admises)


@dataclass
class Hold:
    """Une cale vue par le solveur : emprise, hauteur utile, charge admissible."""

    code: str
    points: list                      # polygone [(x, y), ...] en repère navire
    z_min: float = 0.0
    z_max: float = 0.0
    charge_admissible_t_m2: float = 0.0     # 0 = non renseignée, non contrainte
    nom: str = ""
    # Zones particulières DANS la cale, rectangles (x0, y0, x1, y1[, nom]) en
    # repère navire. Deux natures, distinguées par le nom (`hauteur_libre_de`) :
    # - sans hauteur : zone INTERDITE (épontille, descente, puits, échelle) —
    #   une cale n'est pas forcément entièrement utilisable ;
    # - avec hauteur (« hauteur libre 1.70 m ») : calque de HAUTEUR RÉDUITE,
    #   non bloquant, qui abaisse la hauteur libre sous l'emprise.
    obstacles: list = field(default_factory=list)
    # Zones de charge admissible particulière : [{"nom", "t_m2", "points"}].
    # Là où aucune zone ne s'applique, c'est `charge_admissible_t_m2`.
    zones_charge: list = field(default_factory=list)
    # Les classes IMDG que cette cale ADMET (D-83) : [] = aucune marchandise
    # dangereuse ; ["toutes"] = toutes ; ["3", "9"] = ces classes-là.
    classes_imdg: list = field(default_factory=list)

    def admet_imdg(self, classe):
        return imdg_admis(self.classes_imdg, classe)

    @property
    def zones_interdites(self):
        """Les obstacles qui bloquent la pose (sans hauteur annoncée)."""
        return [o for o in self.obstacles
                if len(o) >= 4 and hauteur_libre_de(o) <= 0]

    @property
    def zones_hauteur(self):
        """[(obstacle, hauteur libre)] : le calque des plafonds bas."""
        out = []
        for o in self.obstacles:
            if len(o) < 4:
                continue
            h = hauteur_libre_de(o)
            if h > 0:
                out.append((o, h))
        return out

    def hauteur_libre_en(self, rect):
        """Hauteur libre (m) sous cette emprise.

        Celle de la cale (z_max − z_min), abaissée par toute zone de hauteur
        réduite que l'emprise touche, ne serait-ce qu'en partie : une pile à
        cheval sous un barrot bas est trop haute quand même — même règle que
        `charge_admissible_en`, l'emprise prend la valeur la plus basse."""
        h = self.hauteur_utile_m
        for o, libre in self.zones_hauteur:
            if _rects_se_chevauchent(rect, o):
                h = min(h, libre)
        return h

    def charge_admissible_en(self, rect):
        """Charge admissible (t/m²) sous cette emprise ; 0 = non contrainte.

        Une emprise entièrement dans une zone prend la valeur de la zone ;
        une emprise à cheval prend la plus petite des valeurs touchées (la
        cale elle-même comprise) — on ne fait pas crédit d'une zone plus
        forte à ce qui n'y tient pas tout entier."""
        touchees = [z for z in self.zones_charge
                    if len(z.get("points", [])) >= 3 and rect_touche_polygone(rect, z["points"])]
        if not touchees:
            return self.charge_admissible_t_m2
        dedans = [z for z in touchees if rect_dans_polygone(*rect, z["points"])]
        if len(touchees) == 1 and dedans:
            v = float(dedans[0].get("t_m2", 0.0))
            return v if v > 0 else self.charge_admissible_t_m2
        valeurs = [float(z.get("t_m2", 0.0)) for z in touchees]
        if not dedans:
            valeurs.append(self.charge_admissible_t_m2)
        valeurs = [v for v in valeurs if v > 0]
        return min(valeurs) if valeurs else 0.0

    def rect_sur_obstacle(self, rect, tol=1e-9):
        """L'emprise mord-elle une zone interdite ? Retourne l'obstacle
        (x0, y0, x1, y1[, nom]) touché, ou None.

        Les zones de hauteur réduite ne comptent pas ici : elles ne bloquent
        pas la pose, elles abaissent `hauteur_libre_en`."""
        for o in self.zones_interdites:
            if _rects_se_chevauchent(rect, o, tol):
                return o
        return None

    @property
    def hauteur_utile_m(self):
        return max(0.0, self.z_max - self.z_min)

    @property
    def bbox(self):
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return min(xs), min(ys), max(xs), max(ys)

    @property
    def aire_m2(self):
        """Aire du polygone (formule du lacet).

        Retenue d'un appel à l'autre : le contrôle de charge moyenne la
        redemande à chaque colis, et une cale décalquée porte soixante
        sommets.

        La clé porte sur le CONTENU du contour, pas sur l'identité de la liste
        ni sur sa longueur : déplacer un sommet dans l'éditeur de plan ne
        change ni l'un ni l'autre, et l'aire périmée continuait à servir de
        dénominateur au contrôle de charge moyenne."""
        pts = self.points
        signature = hash(tuple(map(tuple, pts)))
        cache = getattr(self, "_aire_cache", None)
        if cache is not None and cache[0] == signature:
            return cache[1]
        n = len(pts)
        if n < 3:
            return 0.0
        s = 0.0
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            s += x0 * y1 - x1 * y0
        aire = abs(s) / 2
        try:
            self._aire_cache = (signature, aire)
        except (AttributeError, TypeError):
            pass
        return aire

    @property
    def lcg_m(self):
        x0, _, x1, _ = self.bbox
        return (x0 + x1) / 2


def _accepter_orientation(cls):
    """Fait accepter l'ancien nom `orientation=` au constructeur de `Reglages`.

    Le réglage s'est appelé `orientation` tant qu'il imposait le grand côté du
    colis ; il s'appelle `disposition` depuis qu'il gouverne le sens dans
    lequel la cale se remplit. Le mot a changé, la clé aussi — mais un appel,
    une configuration enregistrée ou un test écrit avant le changement ne
    doivent pas tomber pour autant. L'ancien nom reste donc accepté en
    construction, et se lit et s'écrit comme un attribut (voir la propriété
    `orientation`). Il disparaîtra quand tout le dépôt aura migré."""
    generee = cls.__init__

    def __init__(self, *args, orientation=None, **kw):
        if orientation is not None:
            kw.setdefault("disposition", orientation)
        generee(self, *args, **kw)

    __init__.__doc__ = generee.__doc__
    cls.__init__ = __init__
    return cls


@_accepter_orientation
@dataclass
class Reglages:
    """Ce que l'utilisateur demande au solveur, en TROIS FAMILLES.

    Le bord ne règle pas une liste de cases : il dit *ce qu'il cherche*, *ce
    qu'il s'autorise* et *ce qu'il respecte*. Les champs sont rangés dans cet
    ordre, et la fenêtre du répartiteur porte les mêmes trois titres — une
    case qu'on ne retrouve pas d'un côté à l'autre est une case qu'on ne
    coche pas.

    A · CE QU'ON CHERCHE — `objectif` (la priorité : remplir ou tenir
    l'assiette), `viser_assiette` + `assiette_cible_m`, `equilibrer_tcg` +
    `tcg_cible_m` + `tolerance_tcg_m`.

    B · CE QU'ON S'AUTORISE — `empiler`, `rotation_permise`, `disposition`,
    `melanger_lots`, `respecter_cale_imposee`.

    C · CE QU'ON RESPECTE — `respecter_escales`, `priorite_verticale`.

    Le reste (`pas_m`, `jeu_m`, `gm_min_m`) est de la mécanique : le bord ne
    la règle pas dans cette fenêtre.
    """

    # ------------------------------------------------- A · ce qu'on cherche
    # La PRIORITÉ, et elle seule : CAPACITE = « charger au maximum, l'assiette
    # suit » ; ASSIETTE_GM = « tenir l'assiette visée, quitte à charger
    # moins ». Ce n'est plus le même choix que « vise-t-on une assiette ? » :
    # voir `viser_assiette`.
    objectif: str = ASSIETTE_GM
    # Viser une assiette, oui ou non. Décochée, l'assiette n'entre dans AUCUN
    # départage — même en objectif capacité, où elle départageait jusqu'ici
    # les cales également libres (D-34). Le bord doit pouvoir dire « remplis,
    # je m'occuperai de l'assiette au ballast » : lui laisser une cible qui
    # pèse en douce sur le classement, c'est lui mentir.
    viser_assiette: bool = True
    assiette_cible_m: float = 0.0
    gm_min_m: float = 0.0             # 0 = pas de garde-fou explicite
    # --- gîte : le solveur équilibre bâbord/tribord (retour du bord, v2.14.7)
    # Le TCG que le NAVIRE ENTIER doit avoir. 0 = navire droit, ce qu'on veut
    # presque toujours ; on peut viser autre chose pour compenser une avarie.
    # Ce n'est PAS le TCG de la cargaison : `resoudre` en déduit celui que la
    # cargaison doit avoir, compte tenu de tout ce qui penche déjà (lège,
    # caisses, matériel — `moment_t_hors_cargaison_tm`).
    tcg_cible_m: float = 0.0
    # Chercher la gîte. C'est un QUATRIÈME critère : il ne départage que ce
    # que la capacité et l'assiette laissent à égalité (D-38). Indépendante de
    # `viser_assiette` : assiette seule, gîte seule, les deux, aucune.
    equilibrer_tcg: bool = True
    # Zone morte : en deçà, l'objectif transversal est tenu pour atteint. Sans
    # elle le solveur irait chercher le centimètre de TCG au prix d'un plan
    # moins net, exactement comme le ballastage irait chercher le dixième de
    # degré (README, « Le solutionneur de ballastage »).
    tolerance_tcg_m: float = 0.05

    # --------------------------------------------- B · ce qu'on s'autorise
    # Empiler les colis quand le lot le permet. Décochée, le répartiteur ne
    # pose qu'UNE SEULE COUCHE, quoi que dise le stack du lot — le manifeste
    # n'est pas retouché (le stack reste une donnée de la marchandise), c'est
    # `niveaux_possibles` qui plafonne à 1. Le bord s'en sert quand il n'a ni
    # le matériel ni le temps de gerber à l'escale.
    empiler: bool = True
    # Rotation à 90° : le solveur peut l'employer pour faire tenir un colis de
    # plus. Certains chargements l'interdisent (sens de gerbage, saisines,
    # fourches). None = on suit ce que dit chaque type du catalogue.
    rotation_permise: bool | None = None
    # DISPOSITION dans la cale : AUTO, LONGITUDINALE ou TRANSVERSALE. Elle ne
    # dit pas dans quel sens sont posés les colis — elle dit dans quel sens la
    # cale se REMPLIT, c'est-à-dire dans quel ordre les emplacements sont
    # servis. TRANSVERSALE : d'une muraille à l'autre, et c'est `tcg_cible_m`
    # (la gîte visée) qui décide du côté de départ — tribord, bâbord, ou l'axe
    # vers les deux bords. LONGITUDINALE : d'un bout à l'autre, et c'est
    # l'assiette visée (par le LCG de cargaison que `resoudre` en déduit) qui
    # décide du bout de départ. AUTO : le calepineur prend ce qui loge le plus.
    # Aucune de ces valeurs n'impose plus le grand côté d'un colis : la
    # rotation reste gouvernée par `rotation_permise` et par le catalogue.
    disposition: str = AUTO
    # Mélanger les lots dans une même cale. Décochée, le répartiteur sert un
    # lot à la fois : il finit un lot dans une cale avant d'y commencer le
    # suivant, et il n'ouvre une deuxième cale pour un lot que si la première
    # est pleine. On remplit moins, mais le chargement et le pointage sont
    # tenables au quai. Ce que ça coûte en places est dit dans le rapport.
    melanger_lots: bool = True
    respecter_cale_imposee: bool = True

    # ----------------------------------------------- C · ce qu'on respecte
    # Ordre des escales : ne rien empiler sur ce qui se débarque avant. Le
    # solveur a besoin de l'ordre des escales pour cela — il le reçoit en
    # paramètre de `resoudre` (`ordre_escales`), il ne le devine pas. Ce
    # réglage ne modélise QUE l'empilement, jamais l'accès (voir la docstring
    # de `resoudre` et D-41).
    respecter_escales: bool = False
    # Privilégier les ponts bas (« bas » — meilleur GM) ou les ponts hauts
    # (« haut » — débarquement plus facile). « auto » : le solveur décide
    # comme il l'a toujours fait. C'est un DÉPARTAGE, au même rang que la
    # gîte : ça ne fait jamais perdre un colis.
    priorite_verticale: str = AUTO
    # DEUX CONTRAINTES QU'ON PEUT DÉBRAYER (D-71) : « dans le répartiteur
    # automatique, on devrait pouvoir désactiver des contraintes (message
    # d'avertissement), comme par exemple la charge maximale ». Cochées, la
    # charge de pont admissible (locale et moyenne, t/m²) et la hauteur libre
    # REFUSENT une pose, comme toujours. Décochées, elles ne refusent plus
    # rien : le plan est composé comme si elles n'existaient pas, puis RELU,
    # et ce qui les dépasse est dit dans `Rapport.avertissements` — et
    # signalé sur le plan par les calques de charge et de hauteur (D-12,
    # D-21). On ne fait donc pas taire la contrainte : on la fait parler au
    # lieu de bloquer. Le bord s'en sert pour un chargement qu'il sait
    # exceptionnel (une pièce lourde sur un renfort que le calque ignore) ou
    # pour voir combien il perd à la contrainte.
    respecter_charge_pont: bool = True
    respecter_hauteur_libre: bool = True

    # -------------------------------------------------------- la mécanique
    # Finesse du calepinage : maille de la grille d'occupation (la moitié de
    # cette valeur) et pas de glissement d'une travée qui ne passe pas.
    pas_m: float = 0.05
    # Jeu d'arrimage : le DÉBORDEMENT que l'on prête à chaque colis, de chaque
    # côté (D-64) — « une palette affaissée dont le contenu dépasse un peu ».
    # Deux voisins sont donc séparés de deux fois cette valeur. None = le jeu
    # d'usine du moteur (`JEU_M`). Le plan de cale y met celui que le bord a
    # réglé à la molette : sans cela, remplir à la main et remplir
    # automatiquement ne donnent pas le même plan, et le bord ne peut pas
    # savoir pourquoi.
    jeu_m: float | None = None

    # ------------------------------------------------- l'ancien nom, en alias
    # `orientation` était le nom du réglage tant qu'il imposait le grand côté
    # du colis. Il se lit et s'écrit encore, et vaut exactement `disposition` :
    # le temps que la fenêtre, le plan de cale et les réglages enregistrés du
    # poste du bord aient tous migré. Ce n'est PAS un champ du dataclass — il
    # ne part donc ni dans `fields()` ni dans `replace()`, où il ferait double
    # emploi avec `disposition`.
    @property
    def orientation(self):
        return self.disposition

    @orientation.setter
    def orientation(self, valeur):
        self.disposition = valeur


@dataclass
class Rapport:
    """Ce que le solveur a fait, et ce qu'il n'a pas pu faire."""

    places: dict = field(default_factory=dict)      # code cale -> [Placement]
    non_places: list = field(default_factory=list)  # [(nom, quantité, raison)]
    messages: list = field(default_factory=list)
    lcg_cible_m: float | None = None
    lcg_obtenu_m: float | None = None
    # TCG de l'ensemble posé (épinglées comprises). On annonce le TCG et non
    # une gîte en degrés : le solveur n'a pas le GM sous la main, et une gîte
    # calculée sans GM serait un chiffre inventé (D-38). La gîte réelle, elle,
    # se lit au bandeau de la fenêtre principale une fois le plan appliqué.
    tcg_prevu_m: float | None = None
    # ce que vise la cargaison pour ramener le NAVIRE au TCG demandé, et ce
    # que le navire entier aura avec ce plan (cargaison + tout le reste)
    tcg_cible_cargaison_m: float | None = None
    tcg_navire_prevu_m: float | None = None
    poids_place_t: float = 0.0
    nb_places: int = 0
    # Ce que le plan DÉPASSE quand une contrainte a été débrayée (D-71) :
    # des phrases prêtes à lire, une par cale et par contrainte. Vide tant
    # que tout est respecté — ou que tout est resté coché.
    avertissements: list = field(default_factory=list)
    # Avec quoi chaque cale a été remplie : {code cale: « transversale depuis
    # tribord »}. Le bord règle une DISPOSITION (voir `Reglages`) et doit
    # pouvoir vérifier ce que le calepineur en a fait — en « automatique »
    # surtout, où c'est le calepineur qui choisit. Une cale sans colis posé
    # n'y figure pas : elle n'a été remplie d'aucune façon.
    disposition_par_cale: dict = field(default_factory=dict)
    # vérification finale : ce que donne réellement le plan proposé
    assiette_prevue_m: float | None = None
    dans_domaine: bool | None = None

    def total_par_cale(self):
        return {code: sum(p.poids_total_t for p in lst)
                for code, lst in self.places.items()}


# --------------------------------------------------------------- géométrie
def _point_dans_polygone(x, y, points):
    n = len(points)
    if n < 3:
        return False
    dedans = False
    x1, y1 = points[-1]
    for x2, y2 in points:
        if ((y1 > y) != (y2 > y)) and \
                (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-15) + x1):
            dedans = not dedans
        x1, y1 = x2, y2
    return dedans


def _segments_se_croisent(a, b, c, d):
    """Les segments [a,b] et [c,d] se croisent-ils VRAIMENT ?

    Croisement strict : un simple contact (extrémité posée sur l'autre
    segment, segments alignés) n'en est pas un. C'est ce qu'il faut ici — un
    colis rangé bord à bord contre la muraille la touche sans la mordre.
    """
    def cote(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    d1, d2 = cote(c, d, a), cote(c, d, b)
    d3, d4 = cote(a, b, c), cote(a, b, d)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def rect_dans_polygone(x0, y0, x1, y1, points, pas=0.25, tol=1e-6):
    """Le rectangle tient-il entièrement dans le polygone ?

    Test **exact**, et non échantillonné : les quatre coins doivent être
    dedans, et aucun côté du polygone ne doit couper un côté du rectangle.
    Pour un contour simple, ces deux conditions suffisent — si les coins sont
    dedans et que rien ne traverse, toute la surface est dedans.

    L'ancienne version échantillonnait le pourtour du rectangle tous les
    25 cm : un décrochement plus étroit que le pas — et les cales du navire de référence en
    ont de quelques centimètres depuis que les zones de hauteur réduite font
    partie du contour — passait entre deux points de mesure, et un colis
    pouvait mordre la muraille sans que rien ne le signale. `pas` n'est plus
    utilisé ; il reste pour ne pas casser les appels existants.

    Le rectangle testé est rétréci de `tol` sur ses quatre côtés : le test
    point-dans-polygone est semi-ouvert (un point sur le bord arrière ou
    bâbord compte dedans, sur le bord avant ou tribord dehors), si bien qu'un
    colis rangé contre la muraille avant était refusé alors que le même colis
    contre la muraille arrière passait.
    """
    if len(points) < 3:
        return False
    if x1 - x0 > 2 * tol and y1 - y0 > 2 * tol:
        x0, y0, x1, y1 = x0 + tol, y0 + tol, x1 - tol, y1 - tol
    coins = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    for cx, cy in coins:
        if not _point_dans_polygone(cx, cy, points):
            return False
    cotes = ((coins[0], coins[1]), (coins[1], coins[2]),
             (coins[2], coins[3]), (coins[3], coins[0]))
    prec = points[-1]
    for sommet in points:
        # une arête hors de la boîte du rectangle ne peut rien couper
        if not (min(prec[0], sommet[0]) <= x1 and max(prec[0], sommet[0]) >= x0
                and min(prec[1], sommet[1]) <= y1
                and max(prec[1], sommet[1]) >= y0):
            prec = sommet
            continue
        for a, b in cotes:
            if _segments_se_croisent(a, b, prec, sommet):
                return False
        prec = sommet
    return True


def rect_touche_polygone(rect, points, pas=0.25, tol=1e-6):
    """Le rectangle et le polygone ont-ils une surface commune ?

    Un coin du rectangle dans le polygone, un sommet du polygone dans le
    rectangle, ou un point du contour échantillonné dans le polygone.
    Comme dans `rect_dans_polygone`, le rectangle est rétréci de `tol` : un
    simple contact bord à bord (colis accosté à une zone de charge) ne vaut
    pas surface commune, quel que soit le côté."""
    x0, y0, x1, y1 = rect
    if x1 - x0 > 2 * tol and y1 - y0 > 2 * tol:
        x0, y0, x1, y1 = x0 + tol, y0 + tol, x1 - tol, y1 - tol
    for cx, cy in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        if _point_dans_polygone(cx, cy, points):
            return True
    for px, py in points:
        if x0 < px < x1 and y0 < py < y1:
            return True
    n_x = max(1, int(math.ceil((x1 - x0) / pas)))
    n_y = max(1, int(math.ceil((y1 - y0) / pas)))
    for i in range(1, n_x):
        x = x0 + (x1 - x0) * i / n_x
        if _point_dans_polygone(x, y0, points) or _point_dans_polygone(x, y1, points):
            return True
    for j in range(1, n_y):
        y = y0 + (y1 - y0) * j / n_y
        if _point_dans_polygone(x0, y, points) or _point_dans_polygone(x1, y, points):
            return True
    return False


# ------------------------------------------------------ occupation de la cale
def _intervalles_ligne(points, y):
    """Les segments [x0, x1] où la droite horizontale `y` est DANS le polygone."""
    xs = []
    n = len(points)
    x1, y1 = points[-1]
    for i in range(n):
        x2, y2 = points[i]
        if (y1 <= y < y2) or (y2 <= y < y1):
            xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
        x1, y1 = x2, y2
    xs.sort()
    return [(xs[i], xs[i + 1]) for i in range(0, len(xs) - 1, 2)]


class _Grille:
    """La cale rangée en cellules : ce qui est dans le contour et hors interdit.

    `rect_dans_polygone` est l'appel cher du calepinage — un contour de cale
    décalqué porte trente sommets, et l'ancien solveur le rejouait pour chaque
    position essayée, des dizaines de milliers de fois par cale. On le paie
    désormais UNE fois : la cale est découpée en cellules de 2,5 cm, chaque
    cellule est libre ou non, et le calepinage lit ensuite cette grille au
    lieu de reparcourir le contour.

    La grille est volontairement CONSERVATRICE : une cellule n'est libre que
    si elle est entièrement dans le contour. Elle sert de premier tri rapide,
    et la position finalement retenue est vérifiée une dernière fois par
    `rect_dans_polygone` — jamais l'inverse. Un colis ne sort donc jamais de
    la cale à cause de la grille ; au pire on perd quelques centimètres le
    long d'une muraille oblique.
    """

    def __init__(self, hold: Hold, pas=0.05):
        import numpy as np
        x0, y0, x1, y1 = hold.bbox
        pas = max(0.01, float(pas))
        # Le pas est ajusté pour que la grille recouvre EXACTEMENT la boîte de
        # la cale : sans cela la dernière rangée de cellules déborderait du
        # contour, ou bien une bande de la largeur du pas serait perdue le
        # long de la muraille avant — soit une rangée de palettes en moins.
        self.nx = max(1, int(math.ceil((x1 - x0) / pas)))
        self.ny = max(1, int(math.ceil((y1 - y0) / pas)))
        self.hx = (x1 - x0) / self.nx
        self.hy = (y1 - y0) / self.ny
        self.ox, self.oy = x0, y0
        libre = np.zeros((self.ny, self.nx), dtype=bool)
        eps = 1e-9
        lignes = []
        for j in range(self.ny + 1):
            y = min(max(y0 + j * self.hy, y0 + eps), y1 - eps)
            lignes.append(_intervalles_ligne(hold.points, y))
        for j in range(self.ny):
            # une cellule n'est retenue que si ses deux bords horizontaux sont
            # dans la cale : un liston oblique ne fait alors perdre qu'un pas
            for a0, a1 in lignes[j]:
                for b0, b1 in lignes[j + 1]:
                    c0, c1 = max(a0, b0), min(a1, b1)
                    if c1 - c0 <= 0:
                        continue
                    i0 = int(math.ceil((c0 - x0) / self.hx - eps))
                    i1 = int(math.floor((c1 - x0) / self.hx + eps)) - 1
                    if i1 >= i0 and i1 >= 0:
                        libre[j, max(0, i0):i1 + 1] = True
        for o in hold.zones_interdites:
            ox0, oy0, ox1, oy1 = (float(v) for v in o[:4])
            if ox1 < ox0:
                ox0, ox1 = ox1, ox0
            if oy1 < oy0:
                oy0, oy1 = oy1, oy0
            i0 = int(math.floor((ox0 - x0) / self.hx + eps))
            i1 = int(math.ceil((ox1 - x0) / self.hx - eps)) - 1
            j0 = int(math.floor((oy0 - y0) / self.hy + eps))
            j1 = int(math.ceil((oy1 - y0) / self.hy - eps)) - 1
            if i1 >= i0 and j1 >= j0 and i1 >= 0 and j1 >= 0:
                libre[max(0, j0):j1 + 1, max(0, i0):i1 + 1] = False
        self.libre = libre


def _signature_cale(points, obstacles, pas):
    """Empreinte du CONTENU d'une cale : contour, zones bloquantes, pas.

    Deux cales de même empreinte donnent la même grille ; deux états successifs
    de la même cale n'ont la même empreinte que si rien n'a bougé. D'un
    obstacle on retient ses quatre coordonnées et la hauteur libre qu'il
    annonce — c'est elle, et non son libellé, qui décide s'il bloque la pose
    ou s'il n'est qu'un calque (D-21) ; le reste du nom ne change rien à la
    grille et le porter ici ferait recalculer pour un libellé retouché."""
    return hash((tuple(map(tuple, points)),
                 tuple((tuple(float(v) for v in o[:4]), hauteur_libre_de(o))
                       for o in obstacles if len(o) >= 4),
                 round(float(pas), 6)))


def _grille_de(hold: Hold, pas):
    """La grille de cette cale, calculée une seule fois.

    Elle est rangée SUR la cale : le solveur crée un `Packer` par cale, mais
    aussi un par essai de stratégie, et rebâtir la grille à chaque fois
    coûterait plus cher que tout le reste.

    La signature porte sur le CONTENU, pas sur l'identité des listes : une
    épontille mise en place ou déposée, un sommet déplacé dans l'éditeur, une
    zone interdite redimensionnée ne changent ni `id(points)` ni les
    longueurs — la grille périmée restait servie, et le solveur posait dans
    l'épontille (D-30) ou hors du contour retouché (D-27)."""
    signature = _signature_cale(hold.points, hold.obstacles, pas)
    cache = getattr(hold, "_grille_cache", None)
    if cache is not None and cache[0] == signature:
        return cache[1]
    g = _Grille(hold, pas)
    try:
        hold._grille_cache = (signature, g)
    except (AttributeError, TypeError):      # cale figée : tant pis, on refait
        pass
    return g


def _longueurs_libres(libre, np):
    """Pour chaque cellule, le nombre de cellules libres à sa droite, elle
    comprise. Une colonne de garde est ajoutée à droite (valeur 0) pour que
    l'indexation reste simple."""
    ny, nx = libre.shape
    ar = np.arange(nx)
    faux = np.where(libre, nx, ar)
    prochaine = np.minimum.accumulate(faux[:, ::-1], axis=1)[:, ::-1]
    out = np.zeros((ny, nx + 1), dtype=np.int32)
    out[:, :nx] = prochaine - ar
    return out


def _effacer(libre, g, x0, y0, x1, y1):
    """Marque occupées les cellules que ce rectangle mord."""
    eps = 1e-9
    i0 = int(math.floor((x0 - g.ox) / g.hx + eps))
    i1 = int(math.ceil((x1 - g.ox) / g.hx - eps)) - 1
    j0 = int(math.floor((y0 - g.oy) / g.hy + eps))
    j1 = int(math.ceil((y1 - g.oy) / g.hy - eps)) - 1
    if i1 >= i0 and j1 >= j0 and i1 >= 0 and j1 >= 0:
        libre[max(0, j0):j1 + 1, max(0, i0):i1 + 1] = False


class _Occupation:
    """Ce qui reste libre dans une cale : la grille, moins ce qui est posé.

    Deux familles de tableaux dérivés font toute la vitesse du calepinage :

    - la longueur de la plage libre à DROITE de chaque cellule, et celle
      AU-DESSUS (calculée seulement si l'on range en travers) : savoir si une
      bande de 1,20 m est libre sur toute une rangée devient une comparaison,
      au lieu d'un balayage cellule par cellule ;
    - le compte de cellules libres par colonne et par ligne : de quoi sauter
      d'un coup les parties de la cale déjà pleines, au lieu de les parcourir
      au centimètre. C'est ce qui rend le glanage abordable.
    """

    def __init__(self, grille: _Grille, rects=(), base=None, jeu=JEU_M):
        import numpy as np
        self._np = np
        self.g = grille
        # Jeu de calepinage à laisser entre deux colis, porté par l'occupation
        # : tous les calepinages travaillent sur elle, et l'appelant peut ainsi
        # demander autre chose que la valeur d'usine `JEU_M` — le plan de cale
        # y met le jeu que le bord a réglé à la molette (5 cm pour les
        # saisines, le passage d'un transpalette).
        self.jeu = max(0.0, float(jeu))
        libre = (grille.libre if base is None else base).copy()
        for rect in rects:
            _effacer(libre, grille, *rect)
        self.libre = libre
        ny, nx = libre.shape
        # Longueur de la plage libre à droite de chaque cellule, d'un seul
        # geste : la position de la prochaine cellule occupée, moins la
        # sienne. Le faire colonne par colonne coûtait mille tours de boucle
        # par cale, et il y a une occupation par calepinage essayé.
        self.run_x = _longueurs_libres(libre, np)
        self._run_y = None            # calculé à la demande : la moitié des
                                      # calepinages ne regarde jamais l'axe Y
        cols = libre.sum(axis=0)
        lignes = libre.sum(axis=1)
        self.cum_cols = np.concatenate(([0], np.cumsum(cols)))
        self.cum_lignes = np.concatenate(([0], np.cumsum(lignes)))
        self._plages = {}
        self._travees = {}
        self._rect_max = None

    @property
    def run_y(self):
        """Longueur de la plage libre au-dessus de chaque cellule."""
        if self._run_y is None:
            np = self._np
            self._run_y = _longueurs_libres(self.libre.T, np).T
        return self._run_y

    # --------------------------------------------------------------- indices
    def _cols(self, x0, x1):
        g = self.g
        eps = 1e-9
        i0 = int(math.floor((x0 - g.ox) / g.hx + eps))
        i1 = int(math.ceil((x1 - g.ox) / g.hx - eps)) - 1
        return i0, max(i0, i1)

    def _lignes(self, y0, y1):
        g = self.g
        eps = 1e-9
        j0 = int(math.floor((y0 - g.oy) / g.hy + eps))
        j1 = int(math.ceil((y1 - g.oy) / g.hy - eps)) - 1
        return j0, max(j0, j1)

    def bande_vide(self, a0, a1, axe):
        """Aucune cellule libre dans cette bande : inutile d'y chercher."""
        if axe == "x":
            i0, i1 = self._cols(a0, a1)
            i0, i1 = max(0, i0), min(self.g.nx - 1, i1)
            return i1 < i0 or self.cum_cols[i1 + 1] == self.cum_cols[i0]
        j0, j1 = self._lignes(a0, a1)
        j0, j1 = max(0, j0), min(self.g.ny - 1, j1)
        return j1 < j0 or self.cum_lignes[j1 + 1] == self.cum_lignes[j0]

    def plages(self, a0, a1, axe):
        """Les plages continues, en mètres, où la bande [a0, a1] est libre de
        bout en bout — l'ossature d'une travée."""
        np = self._np
        g = self.g
        if axe == "x":
            i0, i1 = self._cols(a0, a1)
            cle = (i0, i1)
            fait = self._plages.get(cle)
            if fait is not None:
                return fait
            if i0 < 0 or i1 >= g.nx:
                return []
            masque = self.run_x[:, i0] >= (i1 - i0 + 1)
            orig, pas = g.oy, g.hy
        else:
            j0, j1 = self._lignes(a0, a1)
            cle = (-1 - j0, j1)
            fait = self._plages.get(cle)
            if fait is not None:
                return fait
            if j0 < 0 or j1 >= g.ny:
                return []
            masque = self.run_y[j0] >= (j1 - j0 + 1)
            orig, pas = g.ox, g.hx
        m = np.concatenate(([False], masque, [False]))
        bords = np.flatnonzero(m[1:] != m[:-1]).tolist()
        out = [(orig + bords[i] * pas, orig + bords[i + 1] * pas)
               for i in range(0, len(bords), 2)]
        self._plages[cle] = out
        return out

    def plus_grand_rectangle(self):
        """Le plus grand rectangle entièrement libre de la cale."""
        if self._rect_max is None:
            self._rect_max = _plus_grand_rectangle(self.libre, self.g)
        return self._rect_max


def _plus_grand_rectangle(libre, g):
    """Le plus grand rectangle entièrement libre, en coordonnées navire.

    C'est le terrain du calepinage « en blocs » : on ne partitionne pas un
    polygone concave, on partitionne le plus grand rectangle qu'il contient,
    et on garnit le reste en travées. C'est aussi la mesure de ce qu'un
    calepinage LAISSE : entre deux dispositions qui logent autant de colis,
    celle qui abandonne un rectangle franc vaut mieux que celle qui abandonne
    la même surface en copeaux — le lot suivant y tiendra.

    Cherché sur une grille dégrossie (20 cm) : la précision n'y sert à rien,
    la vitesse si."""
    kx = max(1, int(round(0.20 / g.hx)))
    ky = max(1, int(round(0.20 / g.hy)))
    ny, nx = g.ny // ky, g.nx // kx
    if ny < 1 or nx < 1:
        return (0.0, 0.0, 0.0, 0.0)
    grossier = libre[:ny * ky, :nx * kx].reshape(ny, ky, nx, kx).all(axis=(1, 3))
    meilleur = (0, None)
    hauteurs = [0] * (nx + 1)
    for j in range(ny):
        rang = grossier[j].tolist()
        for i in range(nx):
            hauteurs[i] = hauteurs[i] + 1 if rang[i] else 0
        pile = []
        for i in range(nx + 1):
            h = hauteurs[i] if i < nx else 0
            debut = i
            while pile and pile[-1][1] >= h:
                d, hh = pile.pop()
                aire = hh * (i - d)
                if aire > meilleur[0]:
                    meilleur = (aire, (d, i - 1, j - hh + 1, j))
                debut = d
            pile.append((debut, h))
    if meilleur[1] is None:
        return (0.0, 0.0, 0.0, 0.0)
    i0, i1, j0, j1 = meilleur[1]
    return (g.ox + i0 * kx * g.hx, g.oy + j0 * ky * g.hy,
            g.ox + (i1 + 1) * kx * g.hx, g.oy + (j1 + 1) * ky * g.hy)


def _dans_une_plage(plages, u0, u1):
    """[u0, u1] tient-il d'un seul tenant dans l'une des plages libres ?"""
    i = bisect.bisect_right(plages, (u0 + 1e-9,)) - 1
    return i >= 0 and plages[i][1] >= u1 - 1e-9


def _apres(plages, u0):
    """Début de la première plage qui commence après `u0` ; None s'il n'y en a
    plus. Une fois qu'un colis ne tient plus dans la plage où l'on est, aucun
    point plus loin dans la MÊME plage ne l'accueillera : on saute."""
    i = bisect.bisect_right(plages, (u0 + 1e-9,))
    return plages[i][0] if i < len(plages) else None


# ------------------------------------------------------------- stratégies
def _travee(occ: _Occupation, a0, prof, gabarits, ordre, axe, sens=1):
    """Les emplacements d'UNE travée : la bande [a0, a0+prof] de la cale.

    Une travée n'est plus d'un seul tenant dans un seul sens : on y glisse
    l'orientation préférée tant qu'elle passe, et l'autre dès qu'elle seule
    tient dans ce qu'il reste. C'est là que se gagnent les bouts de rangée.

    Chaque orientation n'exige que SA propre profondeur : dans une travée de
    1,20 m, une palette en travers ne réclame que 0,80 m de cale, ce qui la
    fait passer là où la muraille se resserre.
    """
    g = occ.g
    if axe == "x":
        orig, pas, n = g.oy, g.hy, g.ny
    else:
        orig, pas, n = g.ox, g.hx, g.nx
    # Une même bande est réessayée par plusieurs stratégies : on garde le
    # résultat. C'est ce qui rend abordable d'essayer une vingtaine de
    # calepinages sur chaque cale.
    memo = (axe, round(a0, 4), round(prof, 4), sens, tuple(ordre))
    fait = occ._travees.get(memo)
    if fait is not None:
        return fait
    t_min, t_max = orig, orig + n * pas
    plages = {}
    for k in ordre:
        dx, dy = gabarits[k]
        da = dx if axe == "x" else dy
        if da > prof + 1e-9:
            continue
        plages[k] = occ.plages(a0 - occ.jeu / 2, a0 + da + occ.jeu / 2, axe)
    if not plages:
        occ._travees[memo] = []
        return []
    slots = []
    t = t_min if sens > 0 else t_max
    while (t < t_max - 1e-9) if sens > 0 else (t > t_min + 1e-9):
        pose = False
        for k in ordre:
            if k not in plages:
                continue
            dx, dy = gabarits[k]
            db = dy if axe == "x" else dx
            # [u0, u1] : l'emprise plus son jeu de calepinage, accostée au
            # début de la travée (sens +1) ou à sa fin (sens −1)
            u0 = t if sens > 0 else t - db - occ.jeu
            u1 = u0 + db + occ.jeu
            if u0 < t_min - 1e-9 or u1 > t_max + 1e-9:
                continue
            if _dans_une_plage(plages[k], u0, u1):
                b = u0 + occ.jeu / 2
                slots.append([a0, b, k] if axe == "x" else [b, a0, k])
                t = u1 if sens > 0 else u0
                pose = True
                break
        if not pose:
            # rien ne tient ici : sauter à la plage suivante plutôt que
            # d'avancer de cinq centimètres cinquante fois pour rien
            saut = None
            for k in plages:
                if sens > 0:
                    p = _apres(plages[k], t)
                    if p is not None and (saut is None or p < saut):
                        saut = p
                else:
                    for a, b in plages[k]:
                        if b < t - 1e-9 and (saut is None or b > saut):
                            saut = b
            if saut is None:
                break
            t = saut if sens > 0 else min(saut, t - pas)
    occ._travees[memo] = slots
    return slots


def _plan_travees(occ: _Occupation, gabarits, axe, pref, sens=1):
    """Calepinage en travées successives le long de `axe`.

    C'est le calepinage de toujours — les charges se rangent en travées,
    comme on charge réellement — mais la SUITE DES PROFONDEURS n'est plus
    subie : elle est calculée. À chaque position possible on essaie une
    travée de la profondeur de chaque orientation, et une programmation
    dynamique remontant depuis l'avant retient la suite qui loge le plus de
    colis sur toute la longueur de la cale.

    C'est ce qui manquait à l'ancien solveur. Sur une cale de 2,90 m de large,
    trois travées de 0,80 m (2,46 m) tiennent ; mais une travée de 1,20 m de
    palettes en travers suivie de deux travées de 0,80 m (2,86 m) en loge
    davantage — et aucun choix pris travée par travée ne le voit, puisque la
    première travée y paraît moins bonne.

    `sens` = −1 accoste les colis à l'autre extrémité de la travée : sur une
    cale qui se rétrécit, ranger depuis bâbord ou depuis tribord ne donne pas
    le même compte.
    """
    g = occ.g
    if axe == "x":
        a_min, a_max, maille = g.ox, g.ox + g.nx * g.hx, g.hx
        profs = [gab[0] for gab in gabarits]
    else:
        a_min, a_max, maille = g.oy, g.oy + g.ny * g.hy, g.hy
        profs = [gab[1] for gab in gabarits]
    # Pas de glissement quand AUCUNE travée ne passe à cet endroit. La grille
    # est fine (2,5 cm) pour que les emprises tiennent au ras des murailles,
    # mais chercher une travée tous les 2,5 cm reviendrait au balayage
    # exhaustif que ce calepineur remplace. Cinq centimètres suffisent — un
    # colis fait au moins soixante.
    pas = max(maille, 0.05)
    ordre = [pref] + [k for k in range(len(gabarits)) if k != pref]
    mince = min((p for p in profs if p > 0), default=0.0)
    if mince <= 0 or a_max - a_min < mince:
        return []
    # la première travée commence à un demi-jeu de la muraille : une emprise
    # posée pile sur le bordé ne passerait pas le contrôle de contour
    depart = a_min + occ.jeu / 2
    fin_utile = a_max - mince + 1e-9

    # --- 1. les positions de travée réellement atteignables
    # On n'explore que ce qui se suit : après une travée de 1,20 m, la
    # suivante commence à 1,22 m, pas au point de grille d'à côté. C'est ce
    # qui garde le calcul court tout en laissant les profondeurs s'ajuster au
    # centimètre — trois travées de 0,82 m et une de 1,22 m ne tombent pas
    # sur le même pas.
    LIMITE = 4000
    options = {}
    pile = [depart]
    vus = set()
    while pile:
        a = pile.pop()
        cle = round(a, 4)
        if cle in vus or len(vus) >= LIMITE:
            continue          # garde-fou : une cale ne fait pas mille travées
        vus.add(cle)
        choix_a = []
        if not occ.bande_vide(a, a + mince, axe):
            for k in ordre:
                prof = profs[k]
                if prof <= 0 or a + prof > a_max + 1e-9:
                    continue
                s = _travee(occ, a, prof, gabarits, ordre, axe, sens)
                if s:
                    choix_a.append((s, a + prof + occ.jeu))
        options[cle] = (a, choix_a)
        suites = [b for _s, b in choix_a] or [a + pas]
        for b in suites:
            if b <= fin_utile:
                pile.append(b)

    # --- 2. la meilleure suite de travées, en remontant depuis l'avant
    valeur, suite = {}, {}
    for cle in sorted(vus, reverse=True):
        a, choix_a = options[cle]
        meilleure, quoi = 0, None
        for s, b in choix_a:
            v = len(s) + valeur.get(round(b, 4), 0)
            if v > meilleure:
                meilleure, quoi = v, (s, round(b, 4))
        if not choix_a:
            b = round(a + pas, 4)
            if valeur.get(b, 0) > meilleure:
                meilleure, quoi = valeur[b], (None, b)
        valeur[cle], suite[cle] = meilleure, quoi

    # --- 3. on déroule
    slots = []
    cle = round(depart, 4)
    while cle in suite and suite[cle] is not None:
        s, cle = suite[cle]
        if s:
            slots += s
    return slots


def _plan_balayage(occ: _Occupation, gabarits, pref, sens=1):
    """Calepinage « au plus près du bord » : chaque colis va à la première
    place libre, ligne de grille par ligne, en accostant toujours la même
    muraille.

    C'est le calepinage le plus opiniâtre — il ne s'impose aucune travée et
    va nicher un colis dans le moindre creux d'une muraille oblique. Il
    donne des rangées moins nettes, mais sur une cale de forme tourmentée
    (l'avant du navire de référence) il loge des colis qu'aucune travée n'attrape. On le
    garde donc comme candidat, à départager comme les autres.

    `sens` = +1 balaie depuis bâbord, −1 depuis tribord : sur une cale
    dissymétrique, le premier colis posé décide de tout ce qui suit.
    """
    import numpy as np
    g = occ.g
    nx, ny = g.nx, g.ny
    libre = occ.libre.copy()
    run = np.array(occ.run_x[:, :nx])
    ar = np.arange(nx)
    # cellules libres par ligne : un filtre à quatre sous avant de chercher
    # vraiment, décisif quand la cale est déjà presque pleine
    reste = libre.sum(axis=1)
    ordre = [pref] + [k for k in range(len(gabarits)) if k != pref]
    tailles = [(int(math.ceil((dx + occ.jeu) / g.hx - 1e-9)),
                int(math.ceil((dy + occ.jeu) / g.hy - 1e-9)))
               for dx, dy in gabarits]
    slots = []
    j = 0 if sens > 0 else ny - 1
    while 0 <= j < ny:
        pose = False
        for k in ordre:
            w, hh = tailles[k]
            j0 = j if sens > 0 else j - hh + 1
            if w <= 0 or hh <= 0 or j0 < 0 or j0 + hh > ny or w > nx:
                continue
            if reste[j0:j0 + hh].min() < w:
                continue
            m = run[j0:j0 + hh].min(axis=0) if hh > 1 else run[j0]
            idx = np.flatnonzero(m >= w)
            if idx.size == 0:
                continue
            i = int(idx[0])
            slots.append([g.ox + i * g.hx + occ.jeu / 2,
                          g.oy + j0 * g.hy + occ.jeu / 2, k])
            libre[j0:j0 + hh, i:i + w] = False
            reste[j0:j0 + hh] -= w
            bloc = libre[j0:j0 + hh]
            faux = np.where(~bloc, ar, nx)
            run[j0:j0 + hh] = np.minimum.accumulate(
                faux[:, ::-1], axis=1)[:, ::-1] - ar
            pose = True
            break
        if not pose:
            j += sens
    return slots


def _blocs(largeur, hauteur, gabarits, profondeur, jeu=JEU_M, _memo=None):
    """Découpe classique « en blocs » d'un rectangle libre.

    Le rectangle est rempli d'une grille régulière d'une orientation ; ce
    qu'elle laisse (une équerre) se recoupe en deux rectangles, de deux
    façons, chacun repris récursivement. Avec une profondeur de 2 on obtient
    jusqu'à cinq blocs — c'est l'heuristique du chargement de palettes, et
    c'est elle qui remplit les coins qu'un calepinage en travées abandonne.
    """
    if _memo is None:
        _memo = {}
    cle = (round(largeur, 4), round(hauteur, 4), profondeur)
    if cle in _memo:
        return _memo[cle]
    meilleur = (0, [])
    if largeur > 0 and hauteur > 0:
        for k, (dx, dy) in enumerate(gabarits):
            px, py = dx + jeu, dy + jeu
            nx = int((largeur + jeu + 1e-9) // px)
            ny = int((hauteur + jeu + 1e-9) // py)
            if nx <= 0 or ny <= 0:
                continue
            grille = [[i * px, j * py, k] for i in range(nx) for j in range(ny)]
            if len(grille) > meilleur[0]:
                meilleur = (len(grille), grille)
            if profondeur <= 0:
                continue
            uw, uh = nx * px - jeu, ny * py - jeu
            # Le bloc occupe le coin ; ce qu'il laisse est une équerre, qui se
            # recoupe en deux rectangles de deux façons. On essaie les deux.
            coupes = (
                # colonne de droite sur toute la hauteur + bandeau au-dessus
                ((largeur - uw - jeu, hauteur, uw + jeu, 0.0),
                 (uw, hauteur - uh - jeu, 0.0, uh + jeu)),
                # bandeau du dessus sur toute la largeur + colonne de droite
                ((largeur, hauteur - uh - jeu, 0.0, uh + jeu),
                 (largeur - uw - jeu, uh, uw + jeu, 0.0)),
            )
            for (w1, h1, ox1, oy1), (w2, h2, ox2, oy2) in coupes:
                n1, s1 = _blocs(w1, h1, gabarits, profondeur - 1, jeu, _memo)
                n2, s2 = _blocs(w2, h2, gabarits, profondeur - 1, jeu, _memo)
                if len(grille) + n1 + n2 > meilleur[0]:
                    meilleur = (len(grille) + n1 + n2,
                                grille
                                + [[u + ox1, v + oy1, kk] for u, v, kk in s1]
                                + [[u + ox2, v + oy2, kk] for u, v, kk in s2])
    _memo[cle] = meilleur
    return meilleur


def _plan_blocs(occ: _Occupation, gabarits, axe, pref):
    """Blocs dans le plus grand rectangle libre, travées pour le reste."""
    x0, y0, x1, y1 = occ.plus_grand_rectangle()
    w, h = x1 - x0 - occ.jeu, y1 - y0 - occ.jeu
    if w <= 0 or h <= 0:
        return []
    _n, cellules = _blocs(w, h, gabarits, 2, occ.jeu)
    if not cellules:
        return []
    dep_x, dep_y = x0 + occ.jeu / 2, y0 + occ.jeu / 2
    slots = [[dep_x + u, dep_y + v, k] for u, v, k in cellules]
    # le reste de la cale : le bloc devient un obstacle de plus
    reste = _Occupation(occ.g, [(x0, y0, x1, y1)], base=occ.libre, jeu=occ.jeu)
    slots += _plan_travees(reste, gabarits, axe, pref)
    return slots


# ------------------------------------- l'ORDRE dans lequel la cale se remplit
# Un calepinage est une liste d'emplacements ORDONNÉE. Réordonner les mêmes
# emplacements ne change ni le nombre de colis logés ni la surface occupée :
# ça ne change que l'endroit où tombe un lot qui ne remplit pas la cale — donc
# le barycentre du chargement, donc la gîte ou l'assiette. C'est exactement ce
# que le bord veut régler (voir `Reglages.disposition`), et c'est pour cette
# raison que les variantes de progression ci-dessous ne coûtent rien : on ne
# recalcule aucun calepinage, on réordonne celui qu'on a.
#
# C'est aussi ce qui garantit qu'une disposition imposée ne COÛTE JAMAIS un
# colis : le meilleur calepinage de la cale, quelle que soit la façon dont il a
# été composé, peut toujours être re-servi dans le sens demandé. Un réglage de
# progression qui laisserait de la marchandise à quai serait un piège.

# Par quel axe progresse chaque disposition — X est l'axe du navire, Y sa
# largeur — et comment se nomment les trois départs possibles le long de cet
# axe, dans l'ordre attendu par `_sert_en_bandes`.
_AXE_DE = {LONGITUDINALE: "x", TRANSVERSALE: "y"}
_DEPARTS = {"x": ("depuis l'arrière", "depuis l'avant", "depuis le milieu"),
            "y": ("depuis tribord", "depuis bâbord", "depuis l'axe")}


def _sert_en_bandes(slots, gabarits, axe, depart, milieu):
    """Les mêmes emplacements, servis BANDE PAR BANDE le long de `axe`.

    Là où `_par_bandes` s'appuie sur la construction d'un calepinage en travées
    — dont les bandes sont déjà contiguës dans la liste —, celle-ci ne suppose
    RIEN de l'ordre reçu : elle range les emplacements par leur position sur
    l'axe de progression, et, à position égale, le long de la bande. C'est ce
    qu'il faut pour les calepinages qui n'ont pas de travées franches, au
    premier rang desquels les blocs : un pavage régulier n'a pas d'ordre de
    service naturel, mais ses emplacements se rangent en bandes comme les
    autres.

    `depart` : 0 = par le début de l'axe (l'arrière, ou tribord), 1 = par la
    fin (l'avant, ou bâbord), 2 = par le milieu, en alternant de part et
    d'autre. `milieu` est la coordonnée du milieu de la cale sur cet axe.
    """
    i = 0 if axe == "x" else 1
    j = 1 - i

    def cle(s):
        a, b = round(s[i], 4), round(s[j], 4)
        if depart == 2:
            # le tri par distance croissante alterne de lui-même d'un côté et
            # de l'autre ; `a` puis `b` départagent, pour que deux exécutions
            # rendent le même plan au centimètre près
            return (round(abs(s[i] + gabarits[s[2]][i] / 2 - milieu), 4), a, b)
        return ((-a if depart == 1 else a), b)

    return sorted(slots, key=cle)


def _par_bandes(slots, gabarits, axe):
    """Les emplacements d'un calepinage en travées, regroupés par BANDE.

    `_plan_travees` sert ses bandes l'une après l'autre — à X croissant pour
    `axe="x"`, à Y croissant pour `axe="y"` — et remplit chacune de bout en
    bout avant de passer à la suivante. Les emplacements d'une même bande sont
    donc contigus dans la liste, et il suffit de les regrouper pour pouvoir
    servir les bandes dans un autre ordre sans jamais toucher à leur contenu.

    Retourne [[début de la bande, sa profondeur, ses emplacements], ...]."""
    i = 0 if axe == "x" else 1
    bandes = []
    for s in slots:
        a = round(s[i], 4)
        prof = gabarits[s[2]][i]
        if bandes and bandes[-1][0] == a:
            bandes[-1][1] = max(bandes[-1][1], prof)
            bandes[-1][2].append(s)
        else:
            bandes.append([a, prof, [s]])
    return bandes


def _depuis_l_autre_bout(bandes):
    """Les mêmes bandes servies en commençant par la dernière.

    Un plan en travées le long de X part de l'arrière ; renversé, il part de
    l'avant. Chaque bande garde son propre sens de remplissage : on renverse
    l'ordre des rangées, pas les rangées elles-mêmes."""
    return [s for bande in reversed(bandes) for s in bande[2]]


def _depuis_le_milieu(bandes, milieu):
    """Les mêmes bandes servies de la plus proche du milieu à la plus lointaine.

    Le tri par distance croissante alterne naturellement d'un côté et de
    l'autre : c'est le « depuis l'axe vers les deux bords » que demande le
    bord pour la gîte, et le « depuis le milieu vers les deux bouts » pour
    l'assiette. À distance égale, la bande la plus arrière (ou la plus
    tribord) passe la première — sans cela deux exécutions ne donneraient pas
    le même plan."""
    ordre = sorted(bandes,
                   key=lambda b: (round(abs(b[0] + b[1] / 2 - milieu), 4), b[0]))
    return [s for bande in ordre for s in bande[2]]


def _depuis_l_axe(slots, gabarits, milieu):
    """Les emplacements d'un balayage servis du plus proche de l'axe au plus
    lointain.

    Le balayage ne fait pas de bandes franches — il niche chaque colis dans le
    premier creux venu — mais ses emplacements se rangent quand même par
    distance à l'axe, et c'est tout ce qu'il faut pour que la demi-cale
    chargée tombe au milieu plutôt que contre une muraille."""
    return sorted(slots,
                  key=lambda s: (round(abs(s[1] + gabarits[s[2]][1] / 2
                                           - milieu), 4), s[1], s[0]))


def _mesures(slots, gabarits):
    """(surface occupée, étalement longitudinal, étalement transversal).

    Ces trois mesures ne dépendent QUE de l'ensemble des emplacements, jamais
    de l'ordre où on les sert : toutes les variantes de progression d'un même
    calepinage les partagent, et on ne les recalcule pas pour chacune."""
    aire = 0.0
    for _x, _y, k in slots:
        dx, dy = gabarits[k]
        aire += dx * dy
    xs = [s[0] for s in slots]
    ys = [s[1] for s in slots]
    return (round(aire, 6),
            round((max(xs) - min(xs)) if xs else 0.0, 6),
            round((max(ys) - min(ys)) if ys else 0.0, 6))


class _Plan:
    """Un calepinage retenu pour un gabarit : ses emplacements, dans l'ordre."""

    __slots__ = ("slots", "curseur", "nom", "n_places", "reprises")

    def __init__(self, slots, nom="", n_places=0):
        # [x, y, orientation, mort, dernier refus]
        self.slots = [[s[0], s[1], s[2], False, None] for s in slots]
        self.curseur = 0
        self.nom = nom
        self.n_places = n_places        # charges dans la cale au calepinage
        self.reprises = 0               # glanages déjà faits sur ce gabarit


class _IndexPoses:
    """Les emprises déjà posées, rangées par cases de 2 m.

    Sans cet index, savoir si un emplacement est encore libre coûte un
    parcours de toutes les charges de la cale — mille fois mille."""

    CASE = 2.0

    def __init__(self):
        self.cases = {}

    def _cles(self, x0, y0, x1, y1):
        for i in range(int(math.floor(x0 / self.CASE)),
                       int(math.floor(x1 / self.CASE)) + 1):
            for j in range(int(math.floor(y0 / self.CASE)),
                           int(math.floor(y1 / self.CASE)) + 1):
                yield (i, j)

    def ajouter(self, rect):
        for c in self._cles(*rect):
            self.cases.setdefault(c, []).append(rect)

    def touche(self, rect, tol=1e-9):
        x0, y0, x1, y1 = rect
        for c in self._cles(x0, y0, x1, y1):
            for (bx0, by0, bx1, by1) in self.cases.get(c, ()):
                if (x0 < bx1 - tol and bx0 < x1 - tol
                        and y0 < by1 - tol and by0 < y1 - tol):
                    return True
        return False


class Packer:
    """Calepineur : plusieurs calepinages essayés, le meilleur retenu.

    L'ancien calepineur posait les colis un à un, en travées le long de X, le
    premier colis fixant la profondeur de toutes les travées ; la rotation
    n'était qu'un repli quand plus rien ne passait. Sur une cale qui laisse
    une bande de 2 m, il n'y mettait rien.

    Celui-ci raisonne par CALE, pas par colis. Pour un gabarit donné (les
    orientations autorisées du colis), il compose une trentaine de
    calepinages complets de la cale, et garde le meilleur :

    - **en travées**, le long de X puis le long de Y, chacune remplie depuis
      l'une ou l'autre de ses extrémités, avec l'une ou l'autre orientation
      comme orientation préférée. La suite des profondeurs de travées n'est
      pas subie : elle est calculée (`_plan_travees`) ;
    - **en blocs** : le plus grand rectangle libre découpé en cinq blocs
      réguliers au plus, le reste garni en travées ;
    - **au plus près du bord** : chaque colis à la première place libre, ce
      qui va nicher des colis dans les creux d'une muraille oblique.

    Chacun de ces calepinages est en outre proposé dans plusieurs ORDRES DE
    SERVICE (`_candidats`) : les travées le long de X servies depuis
    l'arrière, depuis l'avant ou depuis le milieu ; celles le long de Y depuis
    tribord, depuis bâbord ou depuis l'axe. Réordonner les mêmes emplacements
    ne coûte rien et ne change ni le compte ni la surface — mais c'est cet
    ordre, et lui seul, qui décide où tombe un lot qui ne remplit pas la cale.

    Le meilleur, c'est le plus grand nombre de colis logés, puis la plus
    grande surface occupée, puis le barycentre le plus proche de celui qu'on
    vise — le TCG (`tcg_cible_m`) sauf en disposition longitudinale, où c'est
    le LCG (`lcg_cible_m`) —, puis — pour que le résultat ne dépende jamais de
    l'ordre d'un dictionnaire ni de l'humeur de la machine — le plus faible
    étalement et le rang de la stratégie. Quand le lot ne suffit pas à remplir
    la cale (`attendus`), on regarde en plus ce que chaque calepinage
    laisserait de place au lot suivant.

    `disposition` (AUTO, TRANSVERSALE, LONGITUDINALE) restreint les candidats
    à ceux dont la PROGRESSION est celle que le bord demande : d'une muraille
    à l'autre pour la gîte, d'un bout à l'autre pour l'assiette. Elle ne coûte
    jamais un colis : les calepinages qui ne progressent pas déjà dans ce
    sens-là y sont RE-SERVIS bande par bande au lieu d'être écartés, si bien
    que le meilleur calepinage de la cale reste jouable quel que soit le sens
    demandé. Et elle n'impose jamais le sens d'un colis — `poser` reçoit
    toujours tous les gabarits que la rotation et le catalogue autorisent.

    Les colis se posent ensuite dans l'ordre du calepinage retenu. La
    rotation est donc une DÉCISION prise avant de poser, et non un
    rattrapage. Quand le calepinage est épuisé, il est recomposé sur ce qui
    reste réellement libre — le glanage.

    Ce que le calepineur ne décide pas : la hauteur libre à l'endroit, la
    charge admissible, le gerbage. Ils lui sont passés en `convient` et
    écartent l'emplacement sans arrêter la recherche.
    """

    def __init__(self, hold: Hold, existants=None, pas=0.05, tcg_cible_m=None,
                 jeu_m=None, disposition=AUTO, lcg_cible_m=None):
        self.hold = hold
        self.pas = max(0.01, pas)
        # LE JEU RÉGLÉ EST UN DÉBORDEMENT, pas un écart (D-64). Le bord le
        # décrit ainsi : « une palette qui se serait affaissée et dont le
        # contenu dépasse un peu de ses dimensions ». Chaque colis déborde
        # donc du jeu réglé DE CHAQUE CÔTÉ — d'où deux jeux entre deux
        # voisins, et un seul entre un colis et la muraille.
        #
        # Le calepineur, lui, raisonne depuis toujours en ÉCART TOTAL entre
        # deux colis (`_Occupation.jeu`, dont il laisse la moitié de part et
        # d'autre) : c'est exactement le double. On convertit ici, en un seul
        # endroit, plutôt que de changer toute l'arithmétique du calepinage.
        # None = le jeu d'usine du moteur ; le plan de cale et le répartiteur
        # y passent celui que le bord a réglé à la molette, sans quoi le
        # remplissage automatique ne poserait pas comme la main.
        self.debord_jeu = DEBORD_JEU_M if jeu_m is None else max(0.0, float(jeu_m))
        self.jeu = 2 * self.debord_jeu
        # TCG visé par le calepinage, ou None pour n'en pas tenir compte.
        # À nombre de colis ET surface égaux, deux calepinages se valent pour
        # le chargement mais pas pour le navire : « accostée bâbord » et
        # « accostée tribord » sont l'image l'une de l'autre, et c'est ce
        # choix-là qui fait la gîte. On préfère alors celui dont le barycentre
        # transversal tombe le plus près de la cible (D-38).
        self.tcg_cible_m = (None if tcg_cible_m is None else float(tcg_cible_m))
        # LCG visé par le calepinage, ou None. Pendant du précédent pour
        # l'assiette : en disposition LONGITUDINALE, c'est lui qui dit par quel
        # bout de la cale commencer — l'arrière, l'avant, ou le milieu.
        self.lcg_cible_m = (None if lcg_cible_m is None else float(lcg_cible_m))
        # Dans quel sens la cale se remplit (voir `Reglages.disposition`) :
        # une restriction sur la PROGRESSION des candidats, jamais sur le sens
        # des colis.
        self.disposition = disposition or AUTO
        self.places = list(existants or [])
        # les charges déjà là (épinglées, posées à la main) sont des obstacles
        self.obstacles = list(self.places)
        # La grille de calepinage est deux fois plus fine que le pas demandé :
        # une cellule n'est libre que si elle est ENTIÈREMENT dans la cale, si
        # bien qu'une grille grossière rogne la cale de sa maille tout autour —
        # et une rangée de palettes se perd le long de la muraille.
        self.grille = _grille_de(hold, min(self.pas, 0.05) / 2)
        self._plans = {}
        self._index = _IndexPoses()
        self._connues = set()
        # Combien de colis chaque calepinage a réellement servis : c'est ce qui
        # permet de DIRE au bord avec quelle disposition la cale a été remplie
        # (`disposition_employee`). Un compte, et non le dernier plan composé :
        # une cale reçoit plusieurs gabarits et plusieurs glanages, et ce qui
        # compte est celui qui a posé les colis.
        self._servis = {}
        self._dernier = None
        self._vus_places = self._vus_obstacles = 0
        self._synchroniser()

    # ------------------------------------------------------------ interne
    def _synchroniser(self):
        """Prend acte des charges ajoutées à `places` sans passer par
        `enregistrer` — l'éditeur de plan le fait, et le calepineur ne doit
        pas proposer une place déjà prise. On ne repasse que sur la queue des
        deux listes : les relire en entier à chaque colis coûtait un temps
        carré."""
        for lst, attr in ((self.places, "_vus_places"),
                          (self.obstacles, "_vus_obstacles")):
            n = getattr(self, attr)
            if len(lst) == n:
                continue
            for p in lst[n:]:
                if id(p) not in self._connues:
                    self._connues.add(id(p))
                    self._index.ajouter(_rect_pris(p))
            setattr(self, attr, len(lst))

    def _occupation(self):
        self._synchroniser()
        # ce qui est PRIS, c'est l'encombrement : deux palettes dont les sacs
        # se touchent ne tiennent pas côte à côte (D-39)
        rects = [_rect_pris(p) for p in self.places]
        rects += [_rect_pris(p) for p in self.obstacles if id(p) not in
                  {id(q) for q in self.places}]
        return _Occupation(self.grille,
                           [(x0 - self.jeu / 2, y0 - self.jeu / 2,
                             x1 + self.jeu / 2, y1 + self.jeu / 2)
                            for (x0, y0, x1, y1) in rects],
                           jeu=self.jeu)

    @staticmethod
    def _cle(gabarits):
        return tuple((round(dx, 6), round(dy, 6)) for dx, dy in gabarits)

    @staticmethod
    def _normaliser(gabarits):
        """Les emprises autorisées, sans doublon : un colis carré, ou dont la
        rotation est interdite, n'a qu'un seul sens."""
        vus = []
        for dx, dy in gabarits:
            g = (float(dx), float(dy))
            if g[0] > 0 and g[1] > 0 and g not in vus:
                vus.append(g)
        return vus

    def prochain_centre_x(self, gabarits):
        """Abscisse du centre de la prochaine emprise qui serait posée dans
        cette cale, ou None si le calepinage n'y est pas encore composé.

        Le solveur s'en sert pour choisir la cale : prédire l'effet d'un colis
        sur le LCG en le supposant au MILIEU de la cale est faux dès qu'elle
        n'est qu'à moitié pleine — sur une cale de vingt-quatre mètres, le
        colis suivant se pose quatre mètres plus en arrière, et l'assiette
        obtenue rate la cible."""
        gabarits = self._normaliser(gabarits)
        plan = self._plans.get(self._cle(gabarits))
        if plan is None:
            return None
        slots, i = plan.slots, plan.curseur
        while i < len(slots) and slots[i][3]:
            i += 1
        if i >= len(slots):
            return None
        return slots[i][0] + gabarits[slots[i][2]][0] / 2

    def prochain_centre_y(self, gabarits):
        """Ordonnée du centre de la prochaine emprise posée dans cette cale.

        Pendant du précédent, pour la gîte : deux cales symétriques se valent
        au LCG et à la surface, et c'est l'ordonnée du colis suivant qui dit
        laquelle des deux redresse le navire."""
        gabarits = self._normaliser(gabarits)
        plan = self._plans.get(self._cle(gabarits))
        if plan is None:
            return None
        slots, i = plan.slots, plan.curseur
        while i < len(slots) and slots[i][3]:
            i += 1
        if i >= len(slots):
            return None
        return slots[i][1] + gabarits[slots[i][2]][1] / 2

    def _ecart_tcg(self, slots, gabarits, attendus=None):
        """Écart (m) entre le barycentre transversal d'un calepinage et la
        cible ; 0 quand on ne cherche pas la gîte.

        On ne pèse que les emplacements RÉELLEMENT servis : un calepinage
        composé pour toute la cale mais dont le lot n'occupera que le premier
        tiers ne se juge pas sur les deux tiers qui resteront vides."""
        if self.tcg_cible_m is None or not slots:
            return 0.0
        m = len(slots) if attendus is None else max(1, min(attendus, len(slots)))
        somme = 0.0
        for s in slots[:m]:
            somme += s[1] + gabarits[s[2]][1] / 2
        return round(abs(somme / m - self.tcg_cible_m), 4)

    def _ecart_lcg(self, slots, gabarits, attendus=None):
        """Écart (m) entre le barycentre longitudinal d'un calepinage et la
        cible ; 0 quand on ne vise pas d'assiette.

        Pendant exact de `_ecart_tcg`, sur X : c'est lui qui, en disposition
        LONGITUDINALE, choisit le bout de la cale par lequel commencer. Comme
        pour la gîte, on ne pèse que les emplacements RÉELLEMENT servis — un
        calepinage composé pour toute la cale mais dont le lot n'occupera que
        l'arrière ne se juge pas sur l'avant, qui restera vide."""
        if self.lcg_cible_m is None or not slots:
            return 0.0
        m = len(slots) if attendus is None else max(1, min(attendus, len(slots)))
        somme = 0.0
        for s in slots[:m]:
            somme += s[0] + gabarits[s[2]][0] / 2
        return round(abs(somme / m - self.lcg_cible_m), 4)

    def _candidats(self, occ, gabarits):
        """Tous les calepinages essayés, dans l'ordre où ils sont départagés.

        Chaque candidat est `(nom, progression, emplacements, mesures)`. La
        PROGRESSION dit dans quel sens la cale se remplit — `TRANSVERSALE`
        (d'une muraille à l'autre), `LONGITUDINALE` (d'un bout à l'autre) ou
        None quand le calepinage n'en a pas de naturelle (les blocs, qui
        garnissent un rectangle puis le reste). C'est elle que
        `Reglages.disposition` filtre.

        Les candidats HISTORIQUES viennent en tête et dans leur ordre d'avant :
        à égalité parfaite, c'est le rang qui départage, et l'automatique doit
        continuer à poser exactement comme hier. Les variantes de progression
        ne sont que des RÉORDONNANCEMENTS des mêmes emplacements : elles ne
        coûtent aucun calepinage de plus et partagent les mesures de leur
        parent (surface et étalements n'en dépendent pas).

        Quand une disposition est IMPOSÉE, chaque calepinage qui ne progresse
        pas déjà dans le sens demandé y est re-servi bande par bande
        (`_sert_en_bandes`) : les blocs, mais aussi les travées de l'autre axe
        et les balayages. C'est ce qui garantit qu'une disposition ne coûte
        jamais un colis — le meilleur calepinage de la cale reste disponible,
        quel que soit le sens demandé, puisque seul son ORDRE DE SERVICE
        change. Ces re-services ne sont composés que là : en automatique ils ne
        pourraient rien gagner (même compte, même surface que leur parent) et
        ils déplaceraient le plan d'hier pour rien."""
        g = occ.g
        milieu_x = g.ox + g.nx * g.hx / 2
        milieu_y = g.oy + g.ny * g.hy / 2
        base, variantes = [], []
        # --- en travées. `axe="x"` : des bandes à X successifs, servies de
        # l'arrière vers l'avant — une progression LONGITUDINALE ; chaque bande
        # est remplie en travers depuis tribord (sens +1, on part de Y min) ou
        # depuis bâbord. `axe="y"` : des bandes à Y successifs, servies de
        # tribord vers bâbord — une progression TRANSVERSALE ; chaque bande est
        # remplie dans la longueur depuis l'arrière (sens +1) ou depuis l'avant.
        for pref in range(len(gabarits)):
            for axe in ("x", "y"):
                for sens, rangs in (
                        (1, "rangs accostés tribord" if axe == "x"
                            else "rangs accostés à l'arrière"),
                        (-1, "rangs accostés bâbord" if axe == "x"
                             else "rangs accostés à l'avant")):
                    slots = _plan_travees(occ, gabarits, axe, pref, sens)
                    mesures = _mesures(slots, gabarits)
                    if axe == "x":
                        sens_dit, autre, milieu = (
                            LONGITUDINALE, "depuis l'avant", milieu_x)
                        depart = "depuis l'arrière"
                    else:
                        sens_dit, autre, milieu = (
                            TRANSVERSALE, "depuis bâbord", milieu_y)
                        depart = "depuis tribord"
                    base.append((f"{sens_dit} {depart}, {rangs}, gabarit {pref}",
                                 sens_dit, slots, mesures))
                    if len(slots) < 2:
                        continue        # une bande, rien à réordonner
                    bandes = _par_bandes(slots, gabarits, axe)
                    if len(bandes) < 2:
                        continue
                    milieu_dit = ("depuis le milieu" if axe == "x"
                                  else "depuis l'axe")
                    variantes.append(
                        (f"{sens_dit} {autre}, {rangs}, gabarit {pref}",
                         sens_dit, _depuis_l_autre_bout(bandes), mesures))
                    variantes.append(
                        (f"{sens_dit} {milieu_dit}, {rangs}, gabarit {pref}",
                         sens_dit, _depuis_le_milieu(bandes, milieu), mesures))
        # --- en blocs : un pavage régulier du plus grand rectangle libre, le
        # reste en travées. Aucune progression naturelle — le rectangle se
        # garnit colonne par colonne, le reste comme il peut ; mais ses
        # emplacements se rangent en bandes comme les autres, et une
        # disposition imposée le re-sert donc au lieu de l'écarter (plus bas).
        for axe in ("x", "y"):
            slots = _plan_blocs(occ, gabarits, axe, 0)
            base.append((f"blocs puis travées {axe}", None, slots,
                         _mesures(slots, gabarits)))
        # --- au plus près du bord : un balayage des lignes de grille depuis
        # une muraille, donc une progression TRANSVERSALE (sens +1 = depuis
        # tribord, on part de Y min).
        for pref in range(len(gabarits)):
            for sens, mot in ((1, "depuis tribord"), (-1, "depuis bâbord")):
                slots = _plan_balayage(occ, gabarits, pref, sens)
                mesures = _mesures(slots, gabarits)
                base.append(
                    (f"{TRANSVERSALE} au plus près du bord {mot}, "
                     f"gabarit {pref}", TRANSVERSALE, slots, mesures))
                if len(slots) > 1:
                    variantes.append(
                        (f"{TRANSVERSALE} au plus près du bord depuis l'axe, "
                         f"gabarit {pref}", TRANSVERSALE,
                         _depuis_l_axe(slots, gabarits, milieu_y), mesures))
        # --- les RE-SERVICES, quand une disposition est imposée : tout
        # calepinage qui ne progresse pas déjà dans le sens demandé y est rangé
        # bande par bande. C'est la garantie « une disposition ne coûte jamais
        # un colis » : le meilleur calepinage de la cale — fût-il composé en
        # blocs, ou en travées de l'autre axe — reste jouable dans le sens que
        # le bord a demandé, puisque seul l'ordre de service change.
        axe = _AXE_DE.get(self.disposition)
        if axe is not None:
            milieu = milieu_x if axe == "x" else milieu_y
            for nom, progression, slots, mesures in base:
                if progression == self.disposition or len(slots) < 2:
                    continue
                for depart, mot in enumerate(_DEPARTS[axe]):
                    variantes.append(
                        (f"{self.disposition} {mot}, {nom}", self.disposition,
                         _sert_en_bandes(slots, gabarits, axe, depart, milieu),
                         mesures))
        return base + variantes

    def _plan(self, gabarits, reprise=False, attendus=None, suivants=None):
        """Compose plusieurs calepinages de la cale et retient le meilleur."""
        cle = self._cle(gabarits)
        plan = self._plans.get(cle)
        if plan is not None and not reprise:
            return plan
        occ = self._occupation()
        candidats = self._candidats(occ, gabarits)
        # La DISPOSITION demandée par le bord ne retient que les candidats qui
        # remplissent la cale dans le sens voulu — mais aucun calepinage n'est
        # perdu pour autant : `_candidats` a re-servi dans ce sens-là tous ceux
        # qui n'y progressaient pas. Le repli sur la liste entière ne joue donc
        # que pour un plan d'un seul emplacement, qu'on ne réordonne pas ; il
        # reste là parce qu'un réglage de progression ne doit JAMAIS laisser un
        # colis à quai pour une question d'ordre de service.
        if self.disposition in (TRANSVERSALE, LONGITUDINALE):
            retenus = [c for c in candidats if c[1] == self.disposition]
            candidats = retenus or candidats
        longitudinale = self.disposition == LONGITUDINALE
        notes = []
        for rang, (nom, _progression, slots, mesures) in enumerate(candidats):
            aire, etal_x, etal_y = mesures
            # Le compte d'abord, la surface occupée ensuite, le barycentre du
            # calepinage en troisième, et — pour que deux exécutions donnent le
            # même plan au centimètre près — le plus faible étalement, puis le
            # rang de la stratégie. Rien ici ne dépend de l'ordre d'un
            # dictionnaire.
            #
            # Le barycentre qu'on vise et l'étalement qu'on minimise changent
            # avec la disposition : en LONGITUDINALE on remplit d'un bout à
            # l'autre pour l'assiette, et l'on veut donc des bandes COMPLÈTES
            # en travers — c'est l'étalement transversal qu'il faut serrer. En
            # TRANSVERSALE (et en automatique) c'est l'inverse, comme toujours.
            if longitudinale:
                ecart, etalement = (self._ecart_lcg(slots, gabarits, attendus),
                                    etal_y)
            else:
                ecart, etalement = (self._ecart_tcg(slots, gabarits, attendus),
                                    etal_x)
            notes.append(((len(slots), aire, -ecart, -etalement, -rang),
                          rang, nom, slots))
        notes.sort(reverse=True)
        # Quand le lot ne remplit PAS la cale, le compte brut ne départage
        # plus rien : tous les meilleurs candidats logent le lot entier. Ce
        # qui vaut alors, c'est ce que la cale contiendra une fois TOUT posé.
        # Un calepinage qui étale le lot dans toute la cale et n'y laisse que
        # des copeaux perd contre celui qui le range d'un côté et laisse un
        # rectangle franc au lot suivant — c'est exactement le reproche du
        # bord à l'ancien solveur. On repasse donc les meilleurs au banc
        # d'essai : on retire ce que le lot va réellement occuper, et l'on
        # regarde ce qu'un calepinage rapide remettrait dans ce qui reste,
        # avec l'emprise du lot suivant quand elle est connue.
        #
        # Quand il y a plus de colis que la cale n'en tient, ou au glanage,
        # rien de tout cela : le meilleur calepinage est celui qui en loge le
        # plus, et c'est aussi ce qui coûte le moins cher à calculer.
        #
        # Une exception, et une seule : quand le bord a IMPOSÉ une disposition,
        # c'est qu'il a dit où la demi-cale chargée devait tomber — de tel bord
        # pour la gîte, de tel bout pour l'assiette. Le banc d'essai mesure ce
        # qu'un lot suivant tiendrait encore ; ce lot suivant n'est parfois
        # qu'une hypothèse (`suivants` vaut None dès qu'on ne mélange pas, et
        # pour le dernier lot du manifeste), et remplir depuis l'axe laisse
        # toujours deux chutes là où remplir depuis une muraille en laisse une
        # franche. Laisser le banc trancher, c'est rendre le réglage muet :
        # l'écart au barycentre visé passe donc devant lui — mais SEULEMENT
        # quand une disposition est imposée. En automatique, rien ne change :
        # la capacité garde la main, comme elle l'a toujours eue (D-38).
        partiel = attendus is not None and notes and attendus < len(notes[0][3])
        tete = notes[:6] if (partiel and not reprise) else []
        impose = self.disposition in (TRANSVERSALE, LONGITUDINALE)
        if len(tete) > 1:
            essais = []
            apres = suivants or gabarits
            for note, rang, nom, slots in tete:
                m = min(attendus, len(slots))
                libre = occ.libre.copy()
                for x, y, k in slots[:m]:
                    dx, dy = gabarits[k]
                    _effacer(libre, occ.g, x - self.jeu / 2, y - self.jeu / 2,
                             x + dx + self.jeu / 2, y + dy + self.jeu / 2)
                reste = _Occupation(occ.g, base=libre, jeu=self.jeu)
                glane = max(len(_plan_travees(reste, apres, "x", 0, 1)),
                            len(_plan_travees(reste, apres, "y", 0, 1)))
                # `note[2]` est l'écart au barycentre visé, compté négativement
                essais.append((((note[2], m + glane, note) if impose
                                else (m + glane, note)), rang, nom, slots))
            essais.sort(reverse=True)
            notes = essais + notes
        _note, _rang, nom_max, meilleur = notes[0] if notes else (None, 0, "", [])
        ancien = plan
        plan = _Plan(meilleur, nom_max, len(self.places))
        if ancien is not None:
            plan.reprises = ancien.reprises + 1
        self._plans[cle] = plan
        return plan

    def _valide(self, x, y, dx, dy):
        """Le dernier mot revient au contour exact et aux zones interdites :
        la grille dégrossit, elle ne tranche pas."""
        rect = (x, y, x + dx, y + dy)
        if self.hold.rect_sur_obstacle(rect) is not None:
            return False
        return rect_dans_polygone(x - self.jeu / 2, y - self.jeu / 2,
                                  x + dx + self.jeu / 2, y + dy + self.jeu / 2,
                                  self.hold.points)

    # -------------------------------------------------------------- API
    def poser(self, gabarits, convient=None, cle=None, attendus=None,
              suivants=None):
        """Meilleur emplacement pour un colis, orientation comprise.

        `gabarits` : les emprises autorisées [(dx, dy), ...], celle du
        manifeste d'abord — c'est ici que la rotation se décide.
        `convient(x, y, dx, dy)` écarte un emplacement pour une raison qui
        dépend de l'ENDROIT (plafond bas, charge admissible d'une zone) ;
        `cle` identifie le colis, pour ne pas rejouer cent fois le même refus.
        `attendus` dit combien de colis de ce gabarit restent à poser, et
        `suivants` l'emprise du lot qui viendra ensuite : le calepinage
        s'en sert pour laisser à ce lot-là la meilleure place, au lieu de
        s'étaler dans toute la cale comme le faisait l'ancien.
        Retourne (x, y, indice d'orientation) ou None."""
        gabarits = self._normaliser(gabarits)
        if not gabarits:
            return None
        self._synchroniser()
        plan = self._plan(gabarits, attendus=attendus, suivants=suivants)
        slots = plan.slots
        ecarte = False
        i = plan.curseur
        while i < len(slots) and slots[i][3]:
            i += 1
        plan.curseur = i
        while i < len(slots):
            s = slots[i]
            if s[3]:
                i += 1
                continue
            x, y, k = s[0], s[1], s[2]
            dx, dy = gabarits[k]
            if self._index.touche((x, y, x + dx, y + dy)) \
                    or not self._valide(x, y, dx, dy):
                s[3] = True
                if i == plan.curseur:
                    plan.curseur = i + 1
                i += 1
                continue
            if cle is not None and s[4] == cle:
                i += 1
                continue
            if convient is not None and not convient(x, y, dx, dy):
                s[4] = cle
                ecarte = True
                i += 1
                continue
            self._dernier = (plan, i)
            return (x, y, k)
        # Glanage : le calepinage a été composé sur une cale plus vide qu'elle
        # ne l'est maintenant, et il laisse des chutes entre ses travées. On
        # recompose une fois ou deux sur ce qui reste vraiment libre — c'est
        # là que rentrent les derniers colis, ceux qu'un calepineur d'un seul
        # jet abandonne. Inutile si c'est une contrainte (plafond bas, charge)
        # qui a écarté les emplacements : la place, elle, est bien là.
        if not ecarte and plan.reprises < 3 and plan.n_places < len(self.places):
            plan = self._plan(gabarits, reprise=True, attendus=attendus,
                              suivants=suivants)
            if plan.slots:
                return self.poser(gabarits, convient, cle, attendus, suivants)
        return None

    def place(self, dims, convient=None):
        """Pose une emprise (dx, dy) ; retourne (x, y) ou None.

        Forme historique, sans choix d'orientation : `convient(x, y)`."""
        conv = (None if convient is None
                else (lambda x, y, _dx, _dy: convient(x, y)))
        r = self.poser([tuple(dims)], conv)
        return None if r is None else (r[0], r[1])

    def etat(self):
        """Jeton d'état, à reprendre par `restaurer` si une pose proposée est
        finalement refusée pour une raison que le calepineur ignore."""
        return [(p, p.curseur) for p in self._plans.values()]

    def restaurer(self, jeton):
        for plan, curseur in jeton:
            plan.curseur = min(plan.curseur, curseur)

    def enregistrer(self, placement):
        """Prend acte d'une charge posée : elle devient obstacle pour la suite."""
        self.places.append(placement)
        self._connues.add(id(placement))
        self._index.ajouter(_rect_pris(placement))
        if self._dernier is not None:
            plan, i = self._dernier
            s = plan.slots[i]
            if abs(s[0] - placement.x) < 1e-9 and abs(s[1] - placement.y) < 1e-9:
                s[3] = True
                if i == plan.curseur:
                    plan.curseur = i + 1
                nom = self.disposition_dite(plan.nom)
                if nom:
                    self._servis[nom] = self._servis.get(nom, 0) + 1
            self._dernier = None

    @staticmethod
    def disposition_dite(nom):
        """Le début d'un nom de calepinage : « transversale depuis tribord ».

        Le nom complet dit aussi le sens des rangées et le gabarit préféré —
        utile pour lire un plan à la loupe, illisible dans un compte rendu. Le
        bord veut savoir dans quel sens sa cale s'est remplie, pas quel gabarit
        portait le numéro zéro."""
        return str(nom or "").split(",")[0].strip()

    def disposition_employee(self):
        """Avec quelle disposition cette cale a-t-elle été remplie ?

        Celle qui a posé le plus de colis. Une cale reçoit plusieurs lots, donc
        plusieurs calepinages, et chaque glanage en recompose un : annoncer le
        dernier composé dirait ce que le calepineur a essayé en dernier, pas ce
        qui garnit la cale. Chaîne vide si rien n'y a été posé."""
        if not self._servis:
            return ""
        return max(sorted(self._servis), key=self._servis.get)


def trouver_position(hold: Hold, dims, deja_places, pas=0.05):
    """Première position libre pour une emprise (dx, dy) — usage ponctuel.

    Pour poser une série de charges, préférer `Packer`, qui garde l'état des
    travées d'un appel à l'autre."""
    packer = Packer(hold, deja_places, pas)
    return packer.place(dims)


# --------------------------------------------------------------- aimantation
def _accoste(legal, x0, y0, ux, uy, seuil):
    """Jusqu'où pousser l'emprise dans cette direction avant qu'elle morde.

    C'est ce qui permet d'accoster une muraille **oblique ou en escalier** :
    ses sommets ne donnent aucun repère utile (ils ne sont ni au bon x ni au
    bon y), seule la question « jusqu'où puis-je aller par là ? » a un sens.
    On retourne la distance d'accostage, ou None si rien n'arrête l'emprise
    à portée — pousser dans le vide n'est pas de l'aimantation."""
    if not legal(x0, y0):
        return None
    if legal(x0 + ux * seuil, y0 + uy * seuil):
        return None
    bas, haut = 0.0, seuil
    for _ in range(16):
        milieu = (bas + haut) / 2
        if legal(x0 + ux * milieu, y0 + uy * milieu):
            bas = milieu
        else:
            haut = milieu
    return bas if bas > 1e-4 else None


def _degage(legal, x0, y0, ux, uy, seuil):
    """La plus courte poussée dans cette direction qui rend la position
    acceptable, ou None si rien n'y fait à portée.

    Sert quand le point visé mord déjà — la muraille oblique qu'on pousse du
    coude, le colis lâché à cheval sur son voisin. Sans elle, l'aimantation
    n'avait rien à proposer et la pose partait au refus."""
    if legal(x0, y0):
        return None
    if not legal(x0 + ux * seuil, y0 + uy * seuil):
        return None
    bas, haut = 0.0, seuil
    for _ in range(16):
        milieu = (bas + haut) / 2
        if legal(x0 + ux * milieu, y0 + uy * milieu):
            haut = milieu
        else:
            bas = milieu
    return haut


def aimanter(rect, voisins, bornes=None, jeu=0.0, seuil=0.20, contour=None,
             portee=1.5, interdits=()):
    """Colle une charge à ses voisines et aux parois de la cale.

    `rect` est l'emprise proposée (x0, y0, x1, y1), `voisins` les emprises déjà
    posées, `bornes` la boîte de la cale (x0, y0, x1, y1) ou None, `contour` le
    polygone de la cale (facultatif), `interdits` les zones que la pose refuse
    — rectangles (x0, y0, x1, y1[, nom…]), dont seules les quatre premières
    valeurs sont lues. `jeu` est l'espace laissé entre deux
    colis accostés — zéro pour du jointif, quelques centimètres pour ménager
    saisines ou passage d'un transpalette. `seuil` est la distance
    d'accrochage : au-delà, on laisse la position telle quelle. `portee` borne
    le voisinage examiné : une cale porte jusqu'à deux cents colis, seuls
    ceux qui sont à moins de 1,5 m peuvent servir de repère.

    **Un repère n'en est un que si la pose y serait acceptée.** L'ancienne
    version choisissait le x et le y le plus proche chacun de son côté, sans
    jamais regarder si le rectangle ainsi placé chevauchait un voisin : viser
    l'espace entre deux colis qui ne se touchent pas accrochait le fantôme sur
    l'un des deux, et la pose était refusée pour chevauchement. Ici chaque
    position candidate est vérifiée entière (dans le contour, hors des
    voisins) avant d'être retenue — c'est ce qui fait « attraper »
    l'aimantation dans un trou.

    Quatre familles de repères, toutes utiles à qui range une cale :

    - **accoster** : poser bord à bord contre le voisin qu'on longe ;
    - **aligner** : mettre un bord dans le prolongement d'un bord de voisin
      (le proche comme le lointain), pour que les rangées soient droites même
      quand les colis ne se touchent pas ;
    - **combler un trou** : deux voisins qui ne se touchent pas laissent entre
      eux une place ; si l'emprise y tient (trou ≥ largeur + 2 × jeu, et pas
      démesuré), on propose de s'y glisser, accostée à gauche, à droite, ou
      centrée quand le trou est juste ;
    - **la muraille** : les sommets du contour, la boîte de la cale, et
      l'accostage par poussée, qui plaque l'emprise contre une paroi oblique
      ou en escalier là où aucun sommet ne tombe juste.

    Une **zone interdite** (épontille en place, descente, puits) est traitée
    exactement comme une voisine qu'on ne peut pas déplacer : on s'accoste
    contre, on ne mord jamais dedans. Sans elle, l'aimantation attirait le
    fantôme dans l'épontille et la pose le refusait juste après — or D-30 veut
    le même chemin de refus que le contour, pas un second jeu de règles.

    Retourne le coin (x, y) aimanté. Fonction pure : elle ne touche à rien.
    """
    x0, y0, x1, y1 = rect
    largeur, hauteur = x1 - x0, y1 - y0
    if largeur <= 0 or hauteur <= 0:
        return x0, y0

    # --- le voisinage qui compte -----------------------------------------
    proches = []
    for v in voisins:
        a0, b0, a1, b1 = (float(t) for t in v[:4])
        if (a0 - x1 <= portee and x0 - a1 <= portee
                and b0 - y1 <= portee and y0 - b1 <= portee):
            proches.append((a0, b0, a1, b1))
    if len(proches) > 40:
        proches.sort(key=lambda v: max(v[0] - x1, x0 - v[2], v[1] - y1, y0 - v[3]))
        del proches[40:]

    # Les zones interdites rejoignent le voisinage : ce sont des voisines
    # qu'on ne peut pas pousser. Elles ne subissent pas l'écrêtage à 40 —
    # une cale n'en porte qu'une poignée, et en laisser tomber une rendrait
    # le refus de pose imprévisible. Les coins sont remis dans l'ordre :
    # un rectangle tracé « à l'envers » est courant dans un fichier de
    # géométrie, et `_rects_se_chevauchent` le tolère déjà.
    murs = []
    for o in interdits:
        if len(o) < 4:
            continue
        a0, b0, a1, b1 = (float(t) for t in o[:4])
        a0, a1 = min(a0, a1), max(a0, a1)
        b0, b1 = min(b0, b1), max(b0, b1)
        if (a0 - x1 <= portee and x0 - a1 <= portee
                and b0 - y1 <= portee and y0 - b1 <= portee):
            murs.append((a0, b0, a1, b1))
    bloquants = proches + murs

    def legal(cx, cy):
        """Cette position tiendrait-elle si on posait ? Même question que le
        contrôle de pose (D-27), en plus court : contour, voisins et zones
        interdites."""
        ax1, ay1 = cx + largeur, cy + hauteur
        for (a0, b0, a1, b1) in bloquants:
            if (cx < a1 - 1e-9 and a0 < ax1 - 1e-9
                    and cy < b1 - 1e-9 and b0 < ay1 - 1e-9):
                return False
        if contour and not rect_dans_polygone(cx, cy, ax1, ay1, contour):
            return False
        return True

    # --- les repères, axe par axe ----------------------------------------
    # valeur -> vrai si c'est un vrai repère (et non la position d'origine)
    xs = {round(x0, 9): False}
    ys = {round(y0, 9): False}

    def _noter(table, ref, v):
        """Retient un repère, sauf s'il est hors de portée. Deux repères à
        moins d'un millimètre l'un de l'autre n'en font qu'un : le premier
        nommé gagne, de sorte qu'un sommet de contour l'emporte sur la valeur
        approchée que la poussée en aurait tirée."""
        if abs(v - ref) > seuil + 1e-12:
            return
        for c in table:
            if abs(c - v) <= 1e-3:
                table[c] = True
                return
        table[round(v, 9)] = True

    def note_x(v):
        _noter(xs, x0, v)

    def note_y(v):
        _noter(ys, y0, v)

    for (a0, b0, a1, b1) in bloquants:
        if b0 < y1 - 1e-9 and y0 < b1 - 1e-9:     # on longe ce voisin en Y
            note_x(a1 + jeu)                      # accoster à sa droite
            note_x(a0 - largeur - jeu)            # accoster à sa gauche
        if a0 < x1 - 1e-9 and x0 < a1 - 1e-9:     # on le longe en X
            note_y(b1 + jeu)
            note_y(b0 - hauteur - jeu)
        # aligner un bord sur l'un des siens — le proche ET le lointain :
        # une rangée se lit droite même quand les colis ne se touchent pas
        note_x(a0)
        note_x(a1 - largeur)
        note_x(a1)
        note_x(a0 - largeur)
        note_y(b0)
        note_y(b1 - hauteur)
        note_y(b1)
        note_y(b0 - hauteur)

    # --- combler le trou entre DEUX voisins qui ne se touchent pas --------
    n = min(len(bloquants), 24)
    for i in range(n):
        a = bloquants[i]
        for j in range(n):
            if i == j:
                continue
            b = bloquants[j]
            # un trou en X : a à gauche, b à droite, tous deux en travers de
            # la route de l'emprise
            if (a[2] <= b[0] + 1e-9
                    and a[1] < y1 + seuil and y0 - seuil < a[3]
                    and b[1] < y1 + seuil and y0 - seuil < b[3]):
                trou = b[0] - a[2]
                if largeur + 2 * jeu - 1e-6 <= trou <= largeur + 2 * jeu + 2 * seuil:
                    note_x(a[2] + jeu)
                    note_x(b[0] - jeu - largeur)
                    note_x((a[2] + b[0] - largeur) / 2)
            # le même trou en Y
            if (a[3] <= b[1] + 1e-9
                    and a[0] < x1 + seuil and x0 - seuil < a[2]
                    and b[0] < x1 + seuil and x0 - seuil < b[2]):
                trou = b[1] - a[3]
                if hauteur + 2 * jeu - 1e-6 <= trou <= hauteur + 2 * jeu + 2 * seuil:
                    note_y(a[3] + jeu)
                    note_y(b[1] - jeu - hauteur)
                    note_y((a[3] + b[1] - hauteur) / 2)

    # --- la muraille ------------------------------------------------------
    if contour:
        for vx, vy in contour:
            note_x(vx)
            note_x(vx - largeur)
            note_y(vy)
            note_y(vy - hauteur)
    if bornes:
        cx0, cy0, cx1, cy1 = bornes
        note_x(cx0)
        note_x(cx1 - largeur)
        note_y(cy0)
        note_y(cy1 - hauteur)
    mord = not legal(x0, y0)
    paroi_proche = bool(contour) and not rect_dans_polygone(
        x0 - seuil, y0 - seuil, x1 + seuil, y1 + seuil, contour)
    if mord or paroi_proche:
        # soit une paroi est dans les parages, soit le point visé mord déjà :
        # dans les deux cas on cherche par poussée, seule méthode qui marche
        # contre une muraille oblique ou en escalier (aucun sommet ne tombe
        # au bon x ni au bon y)
        for ux, uy in ((-1.0, 0.0), (1.0, 0.0), (0.0, -1.0), (0.0, 1.0)):
            t = (_degage(legal, x0, y0, ux, uy, seuil) if mord
                 else _accoste(legal, x0, y0, ux, uy, seuil))
            if t is None:
                continue
            if ux:
                note_x(x0 + ux * t)
            else:
                note_y(y0 + uy * t)

    # --- on retient la position ENTIÈRE la meilleure ----------------------
    # D'abord celles qui s'accrochent sur les deux axes : deux colis rangés
    # doivent avoir leurs coins qui coïncident, pas seulement leurs bords
    # alignés chacun sur un voisin différent. À nombre d'axes égal, la plus
    # proche. Et jamais une position que la pose refuserait.
    val_x = sorted(xs.items(), key=lambda kv: abs(kv[0] - x0))[:9]
    val_y = sorted(ys.items(), key=lambda kv: abs(kv[0] - y0))[:9]
    meilleur, note = None, None
    for cx, repere_x in val_x:
        for cy, repere_y in val_y:
            if not legal(cx, cy):
                continue
            axes = (1 if repere_x else 0) + (1 if repere_y else 0)
            score = (-axes, max(abs(cx - x0), abs(cy - y0)))
            if note is None or score < note:
                meilleur, note = (cx, cy), score
    return meilleur if meilleur is not None else (x0, y0)


def bornes_polygone(points):
    """Boîte englobante d'un polygone de cale, pour l'aimantation."""
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


# --------------------------------------------------------------- contraintes
def niveaux_possibles(hold: Hold, ligne, rect=None, empiler=True, hauteur=True):
    """Empilement maximal admissible dans cette cale pour cette charge.

    Sans `rect`, c'est la hauteur utile de la cale qui borne ; avec, c'est la
    hauteur libre SOUS cette emprise (zones de hauteur réduite comprises).

    `empiler=False` (réglage « Empiler les colis quand le lot le permet »
    décoché) plafonne à UNE couche. Le plafond se pose ici, et non en
    retouchant le manifeste : le stack est une donnée de la marchandise
    (D-36), pas un réglage de travail — le lot reste empilable, c'est ce
    chargement-ci qu'on ne gerbe pas. Zéro reste zéro : une charge dont un
    seul exemplaire ne tient pas sous le plafond ne tient toujours pas."""
    n = max(1, int(ligne.gerbable_max))
    if not empiler:
        n = 1
    # `hauteur=False` : la hauteur libre est débrayée (D-71), seul le stack
    # de la marchandise borne — ce qui dépasse sera dit, pas refusé
    if not hauteur:
        return n
    haut = hold.hauteur_libre_en(rect) if rect is not None else hold.hauteur_utile_m
    if ligne.hauteur_m > 0 and haut > 0:
        n = min(n, int(haut / ligne.hauteur_m + 1e-9))
    return max(0, n)


# ------------------------------------------------------- ordre des escales
def rangs_escales(ordre_escales):
    """{clé d'escale: rang dans le voyage} depuis la liste des escales.

    `ordre_escales` est la ligne du navire DANS L'ORDRE (`ports.json`, lue par
    `carene.ports.liste_du_bord`) : le solveur ne la devine pas, il la reçoit.
    La clé ignore la casse, les accents et les séparations, comme la liste des
    escales elle-même : « Pointe à Pitre » et « Pointe-à-Pitre » sont le même
    quai. Une escale absente de la liste n'a pas de rang — et la règle ne dit
    alors rien d'elle, ce qui vaut mieux qu'un rang inventé."""
    from ..ports import cle_nom          # pas de Qt là-dedans non plus
    rangs = {}
    for i, nom in enumerate(ordre_escales or ()):
        cle = cle_nom(nom)
        if cle and cle not in rangs:
            rangs[cle] = i
    return rangs


def rang_de(rangs, port):
    """Le rang de déchargement d'un port, ou None s'il est inconnu."""
    if not rangs or not port:
        return None
    from ..ports import cle_nom
    return rangs.get(cle_nom(port))


def cales_dessous(holds):
    """{code: [codes des cales situées SOUS elle]}.

    La seule superposition que Carène représente entre DEUX LOTS est celle
    des ponts : une pile, elle, est d'un seul lot (D-22), et deux colis d'une
    même cale sont côte à côte, jamais l'un sur l'autre. Une cale est donc
    « sous » une autre quand elle est plus bas (`z_min`) et que les deux
    emprises au sol se recouvrent.

    Le recouvrement se juge sur les BOÎTES ENGLOBANTES, volontairement : plus
    grossier que les polygones, donc plus prudent — on déclare superposées
    deux cales qui ne le sont qu'en partie plutôt que l'inverse. Un réglage
    d'ordre des escales qui laisserait passer un empilement interdit ne
    servirait à rien (D-41)."""
    dessous = {h.code: [] for h in holds}
    for h in holds:
        hx0, hy0, hx1, hy1 = h.bbox
        for autre in holds:
            if autre.code == h.code or autre.z_min >= h.z_min - 1e-9:
                continue
            ax0, ay0, ax1, ay1 = autre.bbox
            if min(hx1, ax1) - max(hx0, ax0) > 1e-9 \
                    and min(hy1, ay1) - max(hy0, ay0) > 1e-9:
                dessous[h.code].append(autre.code)
    return dessous


def trop_haut(hold: Hold, placement):
    """Raison si la pile dépasse la hauteur libre à l'endroit où elle est, ou
    None. Le libellé est le même partout — plan, coupe, liste, solveur."""
    libre = hold.hauteur_libre_en(placement.rect)
    if libre > 0 and placement.hauteur_totale_m > libre + 1e-9:
        return (f"trop haut : {placement.hauteur_totale_m:.2f} m pour "
                f"{libre:.2f} m libre")
    return None


def meme_pile(p, q):
    """Deux colis peuvent-ils former une seule pile ?

    « Identique » = même TYPE et même LOT, pas seulement même type : deux lots
    d'un même type (rhum et café sur palettes EUR) ne se mélangent pas, sinon
    le compte par lot et la couleur du plan deviennent faux. Un colis d'avant
    les lots (sans `lot_id`) se rattache par le type, comme le compte du
    manifeste. Même poids et même hauteur unitaires aussi : le poids et le
    centre de gravité de la pile se calculent sur ceux d'un exemplaire.

    Le **matériel du bord** ne fait jamais pile, ni avec de la marchandise ni
    avec lui-même : un chariot élévateur est un obstacle qu'on contourne, pas
    un socle. Rien ne s'empile dessus, nulle part, par aucun chemin de pose."""
    if getattr(p, "equipement_id", "") or getattr(q, "equipement_id", ""):
        return False
    if not p.type_code or p.type_code != q.type_code:
        return False
    if p.lot_id and q.lot_id and p.lot_id != q.lot_id:
        return False
    return (abs(p.poids_t - q.poids_t) < 1e-9
            and abs(p.hauteur_m - q.hauteur_m) < 1e-9)


def gerbage_refuse(pile, ajout=1):
    """Raison de ne pas ajouter `ajout` exemplaire(s) sur cette pile, ou None :
    la marchandise ne s'empile pas, ou la pile est déjà au maximum. Les
    raisons rendues sont AFFICHÉES telles quelles (barre d'état, refus de
    pose) : elles emploient le mot du bord, « stack » (ex-« gerbage »)."""
    gmax = max(1, int(getattr(pile, "gerbable_max", 1) or 1))
    if gmax <= 1:
        return "non empilable (stack 1)"
    if max(1, pile.niveaux) + ajout > gmax:
        return f"stack maximal ×{gmax} atteint"
    return None


def charge_locale_ok(hold: Hold, placement):
    """La charge admissible SOUS cette emprise (zones comprises) est-elle
    respectée ? Dépend de la position du colis."""
    limite = hold.charge_admissible_en(placement.rect)
    locale = placement.charge_surfacique_t_m2()
    if limite > 0 and locale > limite + 1e-9:
        # Dire ce qu'il faudrait, pas seulement ce qui ne va pas : le bord
        # peut alléger un lot ou le fractionner, à condition de savoir à
        # combien. La limite est celle de l'ENDROIT (zone comprise).
        dx, dy = placement.emprise
        maxi = limite * dx * dy / max(1, placement.niveaux)
        return False, (f"charge locale {locale:.2f} t/m² > {limite:.2f} t/m² "
                       f"admissible ici (au plus {maxi:.2f} t par colis)")
    return True, ""


def charge_moyenne_ok(hold: Hold, placement, deja_places, poids_deja_t=None):
    """La charge moyenne de la cale reste-t-elle admissible une fois ce
    colis ajouté ? Ne dépend pas de la position du colis.

    `poids_deja_t` évite de resommer toute la cale à chaque colis : le
    solveur tient ce total à jour, et refaire la somme mille fois pour mille
    colis coûtait un temps carré."""
    limite = hold.charge_admissible_t_m2
    if limite <= 0:
        return True, ""
    aire = hold.aire_m2
    if aire > 0:
        deja = (sum(p.poids_total_t for p in deja_places)
                if poids_deja_t is None else poids_deja_t)
        total = deja + placement.poids_total_t
        moyenne = total / aire
        if moyenne > limite + 1e-9:
            return False, (f"charge moyenne de la cale {moyenne:.2f} t/m² > "
                           f"{limite:.2f} t/m² admissible")
    return True, ""


def charge_pont_ok(hold: Hold, placement, deja_places, poids_deja_t=None):
    """La charge de pont admissible est-elle respectée, localement et en moyenne ?"""
    ok, why = charge_locale_ok(hold, placement)
    if not ok:
        return ok, why
    return charge_moyenne_ok(hold, placement, deja_places, poids_deja_t)


# --------------------------------------------------------------- LCG cible
def lcg_pour_assiette(navire, poids_total_t, assiette_cible_m,
                      lcg_min=None, lcg_max=None, tol=1e-4, max_iter=60):
    """LCG total donnant l'assiette demandée, par dichotomie sur l'équilibre.

    Retourne None si l'assiette demandée n'est pas atteignable dans le domaine
    des tables — auquel cas il vaut mieux le dire que viser une extrapolation.
    """
    from . import hydrostatics
    # bornes d'assiette de la table : nommées à part des assiettes essayées
    # plus bas, que la boucle d'encadrement appelait aussi t0/t1 — un même nom
    # pour deux choses dans la même fonction est un piège à relecture
    (t_min, t_max), _ = navire.hydro.bounds()
    if not (t_min - 1e-9 <= assiette_cible_m <= t_max + 1e-9):
        return None
    try:
        lo = lcg_min if lcg_min is not None else min(
            min(v["LCB_m"]) for v in navire.hydro.rows_values)
        hi = lcg_max if lcg_max is not None else max(
            max(v["LCB_m"]) for v in navire.hydro.rows_values)
    except (KeyError, ValueError):
        return None

    def trim_de(lcg):
        eq = hydrostatics.solve_equilibrium(navire, poids_total_t, lcg)
        # une solution extrapolée ne vaut rien : on refuse de viser dessus
        return eq.trim_m if eq.dans_domaine else None

    # L'assiette varie de façon monotone avec le LCG, mais les LCG extrêmes
    # donnent des assiettes hors du domaine tabulé. On échantillonne donc
    # d'abord pour trouver un encadrement ENTIÈREMENT valide, puis on affine.
    n_ech = 25
    ech = []
    for i in range(n_ech + 1):
        lcg = lo + (hi - lo) * i / n_ech
        t = trim_de(lcg)
        if t is not None:
            ech.append((lcg, t))
    if len(ech) < 2:
        return None
    paire = None
    for (l0, ta0), (l1, ta1) in zip(ech, ech[1:]):
        if (ta0 - assiette_cible_m) * (ta1 - assiette_cible_m) <= 0:
            paire = (l0, ta0, l1, ta1)
            break
    if paire is None:
        return None            # assiette hors de portée à ce déplacement
    a, ta, b, tb = paire
    for _ in range(max_iter):
        mid = (a + b) / 2
        t_mid = trim_de(mid)
        if t_mid is None:
            return None
        if abs(t_mid - assiette_cible_m) < tol:
            return mid
        if (t_mid - assiette_cible_m) * (ta - assiette_cible_m) > 0:
            a, ta = mid, t_mid
        else:
            b, tb = mid, t_mid
    return (a + b) / 2


def lcg_pour_assiette_au_mieux(navire, poids_total_t, assiette_cible_m, pas=0.1):
    """(LCG, assiette retenue) : l'assiette demandée si elle est atteignable,
    sinon la plus proche qui le soit, dans le domaine des tables.

    Sert au départage de l'objectif capacité : quand la cible n'est pas à
    portée (cargaison légère, navire lège très arrière), il faut quand même
    tirer la cargaison du bon côté, sinon on remplit sans boussole et le plan
    sort des tables. On ne se sert PAS de ce repli pour l'objectif assiette :
    là, une cible hors de portée doit être dite, pas remplacée."""
    lcg = lcg_pour_assiette(navire, poids_total_t, assiette_cible_m)
    if lcg is not None:
        return lcg, assiette_cible_m
    (t0, t1), _ = navire.hydro.bounds()
    essais = []
    k = 1
    while assiette_cible_m - k * pas >= t0 - 1e-9 or assiette_cible_m + k * pas <= t1 + 1e-9:
        for signe in (-1, 1):
            t = assiette_cible_m + signe * k * pas
            if t0 - 1e-9 <= t <= t1 + 1e-9:
                essais.append(t)
        k += 1
        if k > 200:
            break
    for t in essais:
        lcg = lcg_pour_assiette(navire, poids_total_t, t)
        if lcg is not None:
            return lcg, t
    return None, None


# --------------------------------------------------------------- solveur
def resumer_refus(par_motif, causes=()):
    """Une phrase par motif, avec les cales concernées, motifs les plus
    répandus d'abord.

    Un lot refusé partout l'est rarement pour une seule raison : les cales
    du bas sont pleines, celles du haut refusent le poids. Le bord doit lire
    les deux pour savoir quoi faire — alléger le lot, ou libérer de la
    place — et « pas de place » ne dit ni l'un ni l'autre.

    `causes` : les RÉGLAGES qui ont fermé des portes à ce lot (« l'empilement
    est interdit par les réglages », « les lots ne sont pas mélangés »). Elles
    passent en tête, avant les motifs de cale : quand c'est une case cochée
    qui laisse douze colis à quai, le bord doit lire la case, pas déduire le
    refus d'une liste de cales pleines. Une case se décoche ; « pas de place »
    ne se décoche pas."""
    if not par_motif and not causes:
        return "pas de place"
    tete = list(dict.fromkeys(causes))
    if not par_motif:
        return " ; ".join(tete)
    groupes = []
    for why, codes in par_motif.items():
        vus = sorted(dict.fromkeys(codes))
        groupes.append((-len(vus), why, vus))
    groupes.sort()
    return " ; ".join(tete + [f"{', '.join(codes)} : {why}"
                              for _n, why, codes in groupes])


def relire_contraintes(holds, places, charge=True, hauteur=True):
    """Relit un plan avec les contraintes qu'on avait débrayées (D-71) et
    rend les phrases à afficher : une par cale et par contrainte dépassée.

    `places` : {code cale: [Placement]}. `charge` / `hauteur` : ce qu'on
    relit. Rien à dire = liste vide. Le libellé donne le pire écart, pour
    que le bord sache s'il s'agit de 2 % ou du double."""
    out = []
    par_code = {h.code: h for h in holds}
    for code, lst in sorted(places.items()):
        h = par_code.get(code)
        if h is None or not lst:
            continue
        if charge:
            pires = []
            for p in lst:
                ok, _why = charge_locale_ok(h, p)
                if not ok:
                    lim = h.charge_admissible_en(p.rect)
                    pires.append((p.charge_surfacique_t_m2(), lim))
            if pires:
                loc, lim = max(pires)
                out.append(
                    f"{code} : charge de pont débrayée — {len(pires)} colis "
                    f"au-delà de la charge admissible (jusqu'à {loc:.2f} t/m² "
                    f"pour {lim:.2f} t/m² admissible)")
            lim = h.charge_admissible_t_m2
            if lim > 0 and h.aire_m2 > 0:
                moyenne = sum(p.poids_total_t for p in lst) / h.aire_m2
                if moyenne > lim + 1e-9:
                    out.append(
                        f"{code} : charge de pont débrayée — charge moyenne "
                        f"de la cale {moyenne:.2f} t/m² pour {lim:.2f} t/m² "
                        "admissible")
        if hauteur:
            hauts = [(p.hauteur_totale_m, h.hauteur_libre_en(p.rect))
                     for p in lst if trop_haut(h, p) is not None]
            if hauts:
                ht, libre = max(hauts)
                out.append(
                    f"{code} : hauteur libre débrayée — {len(hauts)} pile(s) "
                    f"trop haute(s) (jusqu'à {ht:.2f} m pour {libre:.2f} m "
                    "libre)")
    return out


def resoudre(holds, lignes, reglages: Reglages, epingles=None,
             navire=None, poids_hors_cargaison_t=0.0,
             moment_hors_cargaison_tm=0.0, ordre_escales=None,
             moment_t_hors_cargaison_tm=0.0):
    """Compose un plan de chargement.

    `holds` : liste de `Hold`. `lignes` : manifeste (`ManifestLine`).
    `epingles` : {code cale: [Placement]} conservés tels quels.
    `navire`, `poids_hors_cargaison_t`, `moment_hors_cargaison_tm` : nécessaires
    au seul objectif « assiette visée » (lège + soutes + poids divers).
    `ordre_escales` : la ligne du navire DANS L'ORDRE (noms d'escales), pour
    `Reglages.respecter_escales`. Sans elle, ce réglage ne peut rien dire et
    se tait — le solveur n'invente pas un ordre de voyage.

    Ce que `respecter_escales` tient, et ce qu'il ne tient pas
    ----------------------------------------------------------
    Une seule règle : **on n'empile rien sur ce qui se débarque avant**. Un
    colis posé au-dessus d'un colis qui sort à une escale antérieure serait à
    déplacer au quai suivant — c'est le seul cas que le solveur sait voir
    proprement, et il le refuse. La superposition, ici, c'est la pile
    (`niveaux`, toujours d'un seul lot — D-22) et le PONT : une cale dont
    l'emprise recouvre une cale plus basse est au-dessus d'elle
    (`cales_dessous`).

    Ce n'est PAS un modèle d'accès. « Ce qui est devant bloque ce qui est
    derrière », le chemin des fourches, l'ordre d'ouverture des panneaux : rien
    de tout cela n'est représenté, et un demi-modèle d'accès serait pire que
    pas de modèle — le bord croirait son plan déchargeable alors qu'il ne le
    serait pas (D-41). Deux lots sans port de déchargement, ou de même port, ne
    se contraignent pas.
    """
    epingles = {k: list(v) for k, v in (epingles or {}).items()}
    rapport = Rapport()
    holds_par_code = {h.code: h for h in holds}
    # --- A · ce qu'on cherche : viser une assiette, oui ou non
    # Décochée, l'assiette ne départage RIEN — pas même les cales également
    # libres de l'objectif capacité (D-34). On ramène alors la priorité à
    # « charger au maximum » : tenir une assiette qu'on ne vise pas n'a pas
    # de sens, et laisser le classement s'en servir en douce serait mentir au
    # bord, qui a justement dit qu'il s'en occuperait au ballast.
    vise_assiette = bool(getattr(reglages, "viser_assiette", True))
    objectif = reglages.objectif if vise_assiette else CAPACITE
    # --- B · ce qu'on s'autorise
    empiler = bool(getattr(reglages, "empiler", True))
    # les deux contraintes débrayables (D-71) : True = elles refusent, False
    # = elles sont relues à la fin et dites
    charge_stricte = bool(getattr(reglages, "respecter_charge_pont", True))
    hauteur_stricte = bool(getattr(reglages, "respecter_hauteur_libre", True))
    melanger = bool(getattr(reglages, "melanger_lots", True))
    # --- C · ce qu'on respecte
    priorite_z = getattr(reglages, "priorite_verticale", AUTO)
    # +1 : les ponts bas d'abord (meilleur GM) ; -1 : les ponts hauts d'abord
    # (débarquement plus facile) ; 0 : le solveur comme il l'a toujours fait.
    sens_z = 1.0 if priorite_z == BAS else (-1.0 if priorite_z == HAUT else 0.0)
    rangs_escale = (rangs_escales(ordre_escales)
                    if getattr(reglages, "respecter_escales", False) else {})
    dessous = cales_dessous(holds) if rangs_escale else {}
    dessus = {h.code: [] for h in holds}
    for code, sous in dessous.items():
        for bas in sous:
            dessus[bas].append(code)
    for h in holds:
        rapport.places[h.code] = list(epingles.get(h.code, []))

    # --- développe le manifeste en unités individuelles, lourdes d'abord
    unites = []
    for ligne in lignes:
        for k in range(max(0, int(ligne.quantite))):
            unites.append((ligne, k))
    unites.sort(key=lambda u: (-u[0].poids_t, -u[0].longueur_m * u[0].largeur_m))
    # Combien de colis de la MÊME ligne restent à poser à partir d'ici : le
    # calepineur s'en sert pour ne pas étaler un petit lot sur toute la cale
    # et condamner la place du suivant.
    a_venir = [0] * len(unites)
    # ... et l'emprise du PROCHAIN lot d'une autre ligne : le calepineur s'en
    # sert pour ne pas condamner sa place.
    suivants = [None] * len(unites)
    vus = {}
    prochain = None
    for i in range(len(unites) - 1, -1, -1):
        li = unites[i][0]
        k = id(li)
        vus[k] = vus.get(k, 0) + 1
        a_venir[i] = vus[k]
        suivants[i] = prochain
        if i > 0 and unites[i - 1][0] is not li:
            prochain = [(li.longueur_m, li.largeur_m),
                        (li.largeur_m, li.longueur_m)]

    poids_cargaison = sum(l.poids_total_t for l in lignes)

    # Les charges épinglées (ou déjà posées et conservées) ne sont ni dans le
    # manifeste à répartir ni dans « hors cargaison » : elles pèsent pourtant
    # dans la cale, et le LCG obtenu les compte. Le LCG visé doit donc être
    # celui de l'ensemble « épinglées + manifeste », sinon on vise un point
    # qui ne donne pas l'assiette demandée.
    poids_epingles = 0.0
    moment_epingles = 0.0
    moment_t_epingles = 0.0
    for lst in rapport.places.values():
        for p in lst:
            poids_epingles += p.poids_total_t
            moment_epingles += p.poids_total_t * p.centre[0]
            moment_t_epingles += p.poids_total_t * p.centre[1]

    # --- LCG cible (objectif assiette)
    lcg_cible_cargaison = None
    if not vise_assiette:
        rapport.messages.append(
            "Assiette non visée : le solveur remplit sans jamais regarder "
            "l'assiette. Celle que donne le plan est dite plus bas — à "
            "rattraper au ballast.")
    if navire is not None and poids_cargaison > 0 and vise_assiette:
        total = poids_hors_cargaison_t + poids_epingles + poids_cargaison
        if reglages.objectif == ASSIETTE_GM:
            lcg_total = lcg_pour_assiette(navire, total, reglages.assiette_cible_m)
        else:
            lcg_total, _t = lcg_pour_assiette_au_mieux(
                navire, total, reglages.assiette_cible_m)
        if lcg_total is None:
            if reglages.objectif == ASSIETTE_GM:
                rapport.messages.append(
                    f"Assiette {reglages.assiette_cible_m:+.2f} m hors de portée à "
                    f"{total:.0f} t (domaine des tables) : le solveur répartit au "
                    "mieux sans viser d'assiette.")
        else:
            # LCG de la cargaison en cale (épinglées comprises), comparable
            # au LCG obtenu qui les compte aussi
            brut = ((total * lcg_total - moment_hors_cargaison_tm)
                    / (poids_cargaison + poids_epingles))
            # le LCG de cargaison n'est atteignable que dans l'étendue des cales
            atteignables = [h.lcg_m for h in holds] or [brut]
            lo_c, hi_c = min(atteignables), max(atteignables)
            lcg_cible_cargaison = max(lo_c, min(hi_c, brut))
            rapport.lcg_cible_m = lcg_cible_cargaison
            if reglages.objectif != ASSIETTE_GM:
                pass          # en CAPACITÉ la cible n'est qu'un départage
            elif abs(brut - lcg_cible_cargaison) > 1e-6:
                rapport.messages.append(
                    f"Assiette {reglages.assiette_cible_m:+.2f} m inatteignable "
                    f"avec ce manifeste : il faudrait placer la cargaison à "
                    f"{brut:.1f} m, or les cales s'étendent de {lo_c:.1f} à "
                    f"{hi_c:.1f} m. Le solveur pousse la cargaison au plus "
                    "près de cette limite.")
            else:
                rapport.messages.append(
                    f"LCG de cargaison visé : {lcg_cible_cargaison:.2f} m "
                    f"(assiette {reglages.assiette_cible_m:+.2f} m).")

    # --- TCG cible : celui de la CARGAISON, déduit de celui du NAVIRE
    # Le bord règle un TCG de NAVIRE (0 = droit). Viser ce chiffre avec la
    # seule cargaison — ce que faisait le solveur — ignorait tout ce qui
    # penche déjà : le lège du navire de référence est à +0,168 m (bâbord), les caisses
    # sont rarement symétriques. Avec 1 037 t de lège à 0,168 m, une
    # cargaison posée « à 0 » laisse 174 t·m à bâbord, et le navire penche
    # du côté qu'on croyait avoir compensé — c'est ce que le bord a vu :
    # « il a chargé de manière logique, mais du mauvais côté ». Même
    # raisonnement que pour l'assiette : le moment transversal de tout ce qui
    # n'est pas la cargaison des cales entre dans la cible, et la cargaison
    # doit viser le TCG qui ramène l'ENSEMBLE au chiffre demandé.
    tcg_cible_cargaison = None
    if reglages.equilibrer_tcg:
        poids_cales = poids_cargaison + poids_epingles
        total_t = poids_hors_cargaison_t + poids_cales
        if poids_cales > 0:
            tcg_cible_cargaison = ((total_t * reglages.tcg_cible_m
                                    - moment_t_hors_cargaison_tm) / poids_cales)
            # une cargaison ne se pose pas hors des cales : on borne à
            # l'étendue transversale des cales, et on dit si ça ne suffit pas
            ys = [y for h in holds for y in (h.bbox[1], h.bbox[3])]
            if ys:
                lo_y, hi_y = min(ys), max(ys)
                borne = max(lo_y, min(hi_y, tcg_cible_cargaison))
                if abs(borne - tcg_cible_cargaison) > 1e-6:
                    rapport.messages.append(
                        f"Pour ramener le navire à un TCG de "
                        f"{reglages.tcg_cible_m:+.2f} m, la cargaison devrait "
                        f"avoir un TCG de {tcg_cible_cargaison:+.2f} m, hors "
                        "des cales : le solveur la pousse au plus près du "
                        "bord. Le reste se rattrape au ballast.")
                    tcg_cible_cargaison = borne
            rapport.tcg_cible_cargaison_m = tcg_cible_cargaison
            hors = (moment_t_hors_cargaison_tm / poids_hors_cargaison_t
                    if poids_hors_cargaison_t > 0 else 0.0)
            if abs(hors) > 1e-3:
                rapport.messages.append(
                    f"Hors cargaison (lège, caisses, matériel), le navire est "
                    f"à un TCG de {hors:+.3f} m : la cargaison vise "
                    f"{tcg_cible_cargaison:+.2f} m pour ramener l'ensemble à "
                    f"{reglages.tcg_cible_m:+.2f} m.")
        else:
            tcg_cible_cargaison = reglages.tcg_cible_m

    # --- un calepineur par cale, une fois les CIBLES connues
    # Le calepineur reçoit la disposition demandée et les deux barycentres à
    # viser : le TCG si l'on cherche la gîte, le LCG de cargaison si l'on vise
    # une assiette. C'est ce couple qui, en disposition imposée, choisit le
    # bord ou le bout de la cale par lequel commencer — la gîte visée décide du
    # côté, l'assiette visée décide du bout. Les packers se construisent donc
    # APRÈS le calcul du LCG cible, et non avant.
    packers = {
        h.code: Packer(
            h, rapport.places[h.code], reglages.pas_m,
            tcg_cible_m=tcg_cible_cargaison,
            jeu_m=reglages.jeu_m,
            disposition=getattr(reglages, "disposition", AUTO),
            lcg_cible_m=lcg_cible_cargaison)
        for h in holds}

    # --- état courant des moments, épinglés compris
    poids_courant = poids_epingles
    moment_courant = moment_epingles
    # Le moment TRANSVERSAL est tenu à jour comme le longitudinal : c'est lui
    # qui dit, colis après colis, de quel bord le navire penche déjà et donc
    # quel côté compense (D-38). Le solveur n'en tire jamais une gîte en
    # degrés : il n'a pas le GM.
    moment_t_courant = moment_t_epingles
    equilibrage = bool(reglages.equilibrer_tcg)
    tolerance_tcg = max(0.0, float(reglages.tolerance_tcg_m))

    def cales_candidates(ligne):
        if reglages.respecter_cale_imposee and ligne.cale_imposee:
            h = holds_par_code.get(ligne.cale_imposee)
            return [h] if h else []
        return list(holds)

    # Aire occupée et poids posé, tenus à jour cale par cale. Les resommer à
    # chaque colis coûtait un temps carré : mille colis dans une cale, c'est
    # un million d'additions pour rien, et le solveur doit rester sous la
    # poignée de secondes même sur un chargement complet du navire de
    # référence.
    # la place PRISE, c'est l'encombrement (débord compris) : c'est lui qui
    # dit ce qu'il reste vraiment de libre dans la cale (D-39)
    aire_prise = {h.code: sum(p.encombrement[0] * p.encombrement[1]
                              for p in rapport.places[h.code]) for h in holds}
    poids_pose = {h.code: sum(p.poids_total_t for p in rapport.places[h.code])
                  for h in holds}

    def cle_lot(objet):
        """De quel lot vient ce colis (ou cette ligne) ? Repli par le type
        pour un colis d'avant les lots, comme `meme_pile`."""
        return getattr(objet, "lot_id", "") or getattr(objet, "type_code", "")

    # Quels lots sont déjà dans chaque cale, et à quelles escales ils
    # descendent : deux états tenus à jour au fil des poses, comme l'aire et
    # le poids. Le matériel du bord n'est pas un lot — il ne se débarque pas
    # au commerce et ne mélange rien.
    lots_dans = {h.code: {cle_lot(p) for p in rapport.places[h.code]
                          if not p.est_materiel_bord} for h in holds}
    rangs_dans = {h.code: {r for r in (rang_de(rangs_escale,
                                               p.port_dechargement)
                                       for p in rapport.places[h.code]
                                       if not p.est_materiel_bord)
                           if r is not None} for h in holds}

    def aire_libre(h):
        return h.aire_m2 - aire_prise[h.code]

    def x_prevu(h, gabarits):
        """Où le colis se poserait vraiment dans cette cale.

        Le milieu de la cale est un mauvais devin dès qu'elle n'est pas
        pleine : sur une cale de vingt-quatre mètres à moitié garnie, le colis
        suivant tombe quatre mètres en arrière du milieu, et l'assiette
        obtenue rate la cible de plusieurs centimètres. Le calepineur, lui,
        sait où il mettrait le prochain."""
        if gabarits is not None:
            x = packers[h.code].prochain_centre_x(gabarits)
            if x is not None:
                return x
        return h.lcg_m

    def y_prevu(h, gabarits):
        """Où le colis se poserait vraiment EN TRAVERS dans cette cale.

        Pendant de `x_prevu` : le milieu de la cale ne dit rien de la gîte
        quand le calepinage accoste tout un bord."""
        if gabarits is not None:
            y = packers[h.code].prochain_centre_y(gabarits)
            if y is not None:
                return y
        y0, y1 = h.bbox[1], h.bbox[3]
        return (y0 + y1) / 2

    def ecart_tcg(h, poids_unite, gabarits=None):
        """|TCG| de l'ensemble posé APRÈS ce colis dans cette cale, moins la
        zone morte. C'est le QUATRIÈME critère (D-38) : il ne départage que ce
        que la capacité et l'assiette ont laissé à égalité.

        La zone morte évite d'aller chercher le centimètre de TCG au prix d'un
        plan moins net — même raison qu'au ballastage, où elle vaut 0,2° de
        gîte : sans elle, deux cales également bonnes se départageraient sur
        du bruit de calcul, et le plan cesserait d'être reproductible."""
        p2 = poids_courant + poids_unite
        y = y_prevu(h, gabarits)
        tcg2 = ((moment_t_courant + poids_unite * y) / p2) if p2 > 0 else y
        cible = (tcg_cible_cargaison if tcg_cible_cargaison is not None
                 else reglages.tcg_cible_m)
        return max(0.0, abs(tcg2 - cible) - tolerance_tcg)

    # Étage relatif d'une cale, de 0 (la plus basse) à 1 (la plus haute) :
    # c'est en étages qu'on raisonne, pas en mètres — un navire de quatre
    # ponts et un caboteur de deux ne doivent pas donner des préférences
    # d'intensités différentes pour la même case cochée.
    z_bas = min((h.z_min for h in holds), default=0.0)
    z_haut = max((h.z_min for h in holds), default=0.0)

    def hauteur_relative(h):
        return ((h.z_min - z_bas) / (z_haut - z_bas)) if z_haut > z_bas else 0.0

    def score_principal(h, ligne, poids_unite, gabarits=None):
        """Capacité (ou assiette) seules : le solveur d'avant la gîte."""
        if objectif == CAPACITE:
            # Servir la cale la plus libre — en FRACTION de sa surface, sinon
            # une petite cale (la cave, 35 m²) n'est jamais servie et un bout
            # du navire reste vide. Et, à remplissage voisin, préférer la cale
            # qui rapproche de l'assiette visée : remplir « au plus » sans
            # regarder l'assiette donnait des plans hors du domaine des
            # tables, que le logiciel ne sait même plus calculer.
            frac = aire_libre(h) / h.aire_m2 if h.aire_m2 > 0 else 0.0
            frac -= sens_z * hauteur_relative(h) * POIDS_VERTICAL_CAPACITE
            if lcg_cible_cargaison is None or poids_courant <= 0:
                return -frac
            # Le colis de plus ne déplace le LCG total que de quelques
            # centimètres, quelle que soit la cale : comparer les LCG « après »
            # ne départage rien. On regarde le SENS : si la cargaison est déjà
            # trop en arrière, une cale avant vaut mieux qu'une cale arrière,
            # d'autant plus qu'elle est loin de la cible.
            etendue = max(1.0, max(x.lcg_m for x in holds) - min(x.lcg_m for x in holds))
            erreur = (moment_courant / poids_courant - lcg_cible_cargaison) / etendue
            cote = (h.lcg_m - lcg_cible_cargaison) / etendue
            return -frac + POIDS_ASSIETTE_CAPACITE * erreur * cote
        if lcg_cible_cargaison is None:
            return abs(h.lcg_m - sum(x.lcg_m for x in holds) / len(holds))
        # écart au LCG visé APRÈS avoir posé cette charge dans cette cale
        p2 = poids_courant + poids_unite
        m2 = moment_courant + poids_unite * x_prevu(h, gabarits)
        lcg2 = m2 / p2 if p2 > 0 else h.lcg_m
        # à écart égal, préférer la cale la plus basse (GM) — sauf si le
        # bord a demandé les ponts hauts, auquel cas on ne peut pas descendre
        # les charges dans son dos
        return abs(lcg2 - lcg_cible_cargaison) + 0.02 * h.z_min * (
            -1.0 if priorite_z == HAUT else 1.0)

    def score_cale(h, ligne, poids_unite, gabarits=None):
        """Le classement des cales : (lot en cours, principal, gîte, pont).

        L'assiette et la capacité gardent la main — les termes suivants ne
        sont lus que si le premier est le même, ce qui est le cas courant de
        deux cales symétriques : même LCG, même surface, et le navire qui
        penche (D-38).

        Devant tout : quand les lots ne se mélangent pas, une cale où CE lot
        est déjà commencé passe avant une cale vierge — c'est ce qui évite
        d'éclater un lot sur trois cales quand une seule suffisait.

        Derrière la gîte : la priorité verticale, au même rang qu'elle. Elle
        ne départage donc que des cales que tout le reste laisse à égalité,
        et ne fait jamais perdre un colis."""
        base = score_principal(h, ligne, poids_unite, gabarits)
        rang = 0 if (melanger or cle_lot(ligne) in lots_dans[h.code]) else 1
        if not equilibrage and not sens_z:
            return (rang, base, 0.0, 0.0)
        # arrondi au micromètre : deux cales que rien ne sépare vraiment ne
        # doivent pas être départagées par le dernier bit d'un flottant
        return (rang, round(base, 6),
                ecart_tcg(h, poids_unite, gabarits) if equilibrage else 0.0,
                sens_z * h.z_min)

    def _pile_hors_escales(pile, rang):
        """Ajouter une couche à cette pile la mettrait-il sur un colis qui se
        débarque avant ? Une pile est d'un seul lot (D-22), donc d'un seul
        port : le cas ne se présente que pour un colis d'avant les lots,
        rattaché par le type. La règle vaut quand même là — une règle qui
        s'arrête au cas qu'on a en tête n'en est pas une."""
        if not rangs_escale or rang is None:
            return False
        r = rang_de(rangs_escale, getattr(pile, "port_dechargement", ""))
        return r is not None and r < rang

    def escale_refuse(h, rang):
        """Poser un colis de ce rang de déchargement dans cette cale
        empilerait-il quelque chose sur ce qui se débarque avant ? Le motif,
        ou None. Sans rang connu (pas de port au manifeste, ou port hors de
        la liste des escales), la règle ne dit rien."""
        if rang is None:
            return None
        for code in dessous.get(h.code, ()):
            for r in rangs_dans.get(code, ()):
                if r < rang:
                    return (f"ordre des escales : {code}, dessous, se "
                            "débarque avant")
        for code in dessus.get(h.code, ()):
            for r in rangs_dans.get(code, ()):
                if r > rang:
                    return (f"ordre des escales : {code}, au-dessus, se "
                            "débarque après")
        return None

    refus = {}
    # Les emplacements qu'une contrainte d'ENDROIT a fait écarter dans chaque
    # cale (plafond bas, zone de charge faible) : quand il ne reste plus de
    # place, c'est souvent parce qu'une partie de la cale n'a pas pu servir,
    # et « pas de place libre » sans cette explication laisserait croire à
    # une cale pleine.
    ecartes = {}
    # Ce que les RÉGLAGES ont coûté, en colis restés à quai. Un compte rendu
    # qui dit « plus de place » là où c'est une case cochée qui refuse envoie
    # le bord chercher de la place qu'il a déjà (D-34).
    coute = {"empiler": 0, "melanger": 0, "escales": 0}
    for i_unite, (ligne, _k) in enumerate(unites):
        pose = False
        raisons = []
        causes = []
        rang_ligne = rang_de(rangs_escale, ligne.port_dechargement)
        # les emprises autorisées pour ce colis, une fois pour toutes : le
        # choix de la cale s'appuie dessus (où le colis irait vraiment), et
        # le calepineur y décide de l'orientation
        modele_g = ligne.to_placement()
        tourne = (ligne.rotation_permise if reglages.rotation_permise is None
                  else (reglages.rotation_permise and ligne.rotation_permise))
        # Le calepineur raisonne en ENCOMBREMENT, jamais en emprise : ce
        # qu'il faut faire tenir dans la cale, c'est la palette PLUS ce qui
        # dépasse. Les positions qu'il rend sont donc des coins
        # d'encombrement, ramenés au coin de la palette par `debord` juste
        # avant de poser (D-39).
        debord = max(0.0, float(getattr(ligne, "debord_m", 0.0) or 0.0))
        modele_g.rot = 0
        droit = modele_g.encombrement
        modele_g.rot = 90
        travers = modele_g.encombrement
        # TOUS les gabarits autorisés partent au calepineur : c'est lui qui
        # décide du sens de chaque colis, pour en loger le plus. Plus aucun
        # réglage n'impose le grand côté — `disposition` gouverne l'ORDRE dans
        # lequel la cale se remplit, pas le sens des colis (retour du bord).
        # Seuls la case « tourner de 90° » et le catalogue peuvent n'en
        # laisser qu'un.
        gabarits = [droit]
        rots = [0]
        if tourne and travers != droit:
            gabarits.append(travers)
            rots.append(90)
        # Les portes que les RÉGLAGES ferment avant même de regarder la
        # place : un lot étranger déjà dans la cale quand on ne mélange pas,
        # un empilement interdit par l'ordre des escales. On les écarte ici
        # plutôt que dans le score — une préférence qui cède dès que la place
        # manque ne serait pas un réglage, ce serait un vœu.
        candidates = []
        classe_imdg = str(getattr(ligne, "classe_imdg", "") or "")
        for h in cales_candidates(ligne):
            # MARCHANDISE DANGEREUSE (D-83) : seulement dans une cale qui admet
            # sa classe. Ce n'est pas un réglage qu'on décoche : c'est une
            # règle du navire, écrite dans ses plans.
            if classe_imdg and not h.admet_imdg(classe_imdg):
                raisons.append((h.code, f"n'admet pas la classe IMDG {classe_imdg}"))
                continue
            if not melanger:
                etrangers = lots_dans[h.code] - {cle_lot(ligne)}
                if etrangers:
                    raisons.append((h.code, "un autre lot y est déjà"))
                    causes.append("les lots ne sont pas mélangés")
                    continue
            if rangs_escale:
                pourquoi = escale_refuse(h, rang_ligne)
                if pourquoi is not None:
                    raisons.append((h.code, pourquoi))
                    causes.append("l'ordre des escales interdit d'empiler là")
                    continue
            candidates.append(h)
        if not empiler and ligne.gerbable_max > 1:
            causes.append("l'empilement est interdit par les réglages")
        for h in sorted(candidates,
                        key=lambda hh: score_cale(hh, ligne, ligne.poids_t,
                                                  gabarits)):
            n = niveaux_possibles(h, ligne, empiler=empiler, hauteur=hauteur_stricte)
            if n <= 0:
                raisons.append((h.code, "hauteur utile insuffisante"))
                continue
            deja = rapport.places[h.code]

            # Empiler sur une pile identique déjà posée coûte moins de
            # surface. « Identique » au sens de `meme_pile` : même type ET
            # même lot (D-22 — deux lots d'un même type ne se mélangent pas,
            # repli par le type pour un colis d'avant les lots). La pile doit
            # rester sous le gerbage maximal du lot et sous la hauteur libre
            # À SON ENDROIT — un barrot bas au-dessus d'elle compte, pas
            # seulement la hauteur de la cale.
            empile = None
            if n > 1:                 # marchandise non gerbable : rien à chercher
                modele = ligne.to_placement()
                for p in deja:
                    # `meme_pile` écarte déjà le matériel du bord ; on le
                    # redit ici parce que c'est la règle qui compte : le
                    # solveur ne l'empile pas et ne le déplace pas.
                    if (not p.epingle and not getattr(p, "equipement_id", "")
                            and meme_pile(p, modele)
                            and p.niveaux < niveaux_possibles(
                                h, ligne, p.rect, empiler=empiler,
                                hauteur=hauteur_stricte)
                            and not _pile_hors_escales(p, rang_ligne)):
                        empile = p
                        break
            if empile is not None:
                essai = Placement(**{**empile.to_dict(),
                                     "niveaux": empile.niveaux + 1})
                ok, why = charge_pont_ok(
                    h, essai, None,
                    poids_pose[h.code] - empile.poids_total_t)
                if not charge_stricte:
                    ok = True             # débrayée : dite après, pas refusée
                if ok:
                    empile.niveaux += 1
                    poids_pose[h.code] += ligne.poids_t
                    poids_courant += ligne.poids_t
                    moment_courant += ligne.poids_t * empile.centre[0]
                    moment_t_courant += ligne.poids_t * empile.centre[1]
                    rapport.nb_places += 1
                    rapport.poids_place_t += ligne.poids_t
                    pose = True
                    break
                raisons.append((h.code, why))

            # sinon, poser une nouvelle emprise. La ROTATION est une décision
            # du calepinage, pas un rattrapage : les deux orientations
            # autorisées partent ensemble au calepineur, qui choisit celle qui
            # fait entrer le plus de colis dans la cale. Un type que le
            # catalogue déclare sans rotation, ou un réglage qui l'interdit,
            # n'en propose qu'une.
            place = ligne.to_placement()
            # la charge MOYENNE de la cale ne dépend pas de l'endroit : on
            # la contrôle une fois, avant de chercher une place
            place.niveaux = 1
            place.rot = 0
            ok, why = charge_moyenne_ok(h, place, None, poids_pose[h.code])
            if not ok and charge_stricte:
                raisons.append((h.code, why))
                continue
            packer = packers[h.code]
            # La charge admissible LOCALE et la hauteur libre dépendent de
            # l'endroit (zones de charge, zones de hauteur réduite) : elles se
            # contrôlent là où le colis irait vraiment, orientation comprise.
            # Le calepineur écarte l'emplacement et passe au suivant.
            refus_local = []

            def convient(x, y, dx, dy, place=place, refus_local=refus_local,
                         droit=gabarits[0]):
                # le calepineur essaie les deux orientations : le contrôle
                # doit porter sur celle qu'il propose, pas sur celle du
                # manifeste — l'emprise et donc la charge au m² en dépendent
                place.rot = 0 if (dx, dy) == droit else 90
                # (x, y) est le coin de l'ENCOMBREMENT : la palette, elle,
                # commence un débord plus loin — et c'est elle que la hauteur
                # libre et la charge admissible regardent
                place.x, place.y = x + debord, y + debord
                why = trop_haut(h, place) if hauteur_stricte else None
                ok = why is None
                if ok and charge_stricte:
                    ok, why = charge_locale_ok(h, place)
                if not ok:
                    compte = ecartes.setdefault(h.code, {})
                    compte[why] = compte.get(why, 0) + 1
                    if not refus_local:
                        refus_local.append(why)
                return ok

            jeton = packer.etat()
            # `suivants` dit au calepineur de ne pas condamner la place du
            # PROCHAIN lot dans cette cale. Quand on ne mélange pas les lots,
            # ce prochain lot n'y entrera jamais : lui garder de la place
            # reviendrait à laisser un trou pour personne. On le tait.
            pos = packer.poser(gabarits, convient, cle=(ligne.lot_id, 1),
                               attendus=a_venir[i_unite],
                               suivants=(suivants[i_unite] if melanger
                                         else None))
            if pos is None:
                if refus_local:
                    raisons.append((h.code, refus_local[0]))
                else:
                    # Une cale aux trois quarts vide qui « n'a pas de place »
                    # n'en a pas parce que chaque emplacement a été écarté par
                    # une contrainte d'endroit : c'est CE motif qu'il faut
                    # dire, pas « pas de place ». Une cale pleine, elle, l'est.
                    compte = ecartes.get(h.code, {})
                    if compte and aire_libre(h) > 0.25 * h.aire_m2:
                        motif = max(compte, key=compte.get)
                        raisons.append((h.code, motif))
                    else:
                        raisons.append((h.code, "pas de place libre"))
                continue
            place.x, place.y = pos[0] + debord, pos[1] + debord
            k = pos[2]
            place.rot = rots[k]
            place.niveaux = 1
            ok, why = charge_pont_ok(h, place, None, poids_pose[h.code])
            if not ok and charge_stricte:
                packer.restaurer(jeton)
                raisons.append((h.code, why))
                continue
            packer.enregistrer(place)
            deja.append(place)
            lots_dans[h.code].add(cle_lot(place))
            if rang_ligne is not None:
                rangs_dans[h.code].add(rang_ligne)
            aire_prise[h.code] += place.encombrement[0] * place.encombrement[1]
            poids_pose[h.code] += place.poids_total_t
            poids_courant += place.poids_total_t
            moment_courant += place.poids_total_t * place.centre[0]
            moment_t_courant += place.poids_total_t * place.centre[1]
            rapport.nb_places += 1
            rapport.poids_place_t += place.poids_total_t
            pose = True
            break
        if not pose:
            # TOUTES les raisons, de TOUTES les cales : n'en garder que deux
            # montrait « pas de place libre » sur les cales pleines et
            # cachait que les cales vides refusaient pour la charge de pont —
            # et le bord concluait que le solveur s'arrêtait sans raison.
            key = ligne.nom
            entree = refus.setdefault(key, [0, {}, []])
            entree[0] += 1
            for code, why in raisons:
                entree[1].setdefault(why, []).append(code)
            for cause in dict.fromkeys(causes):
                if cause not in entree[2]:
                    entree[2].append(cause)
            if not empiler and ligne.gerbable_max > 1:
                coute["empiler"] += 1
            if any(c.startswith("les lots") for c in causes):
                coute["melanger"] += 1
            if any(c.startswith("l'ordre") for c in causes):
                coute["escales"] += 1

    for nom, (qte, par_motif, causes) in refus.items():
        rapport.non_places.append((nom, qte, resumer_refus(par_motif, causes)))

    # Ce que chaque réglage a coûté, en toutes lettres : une case se décoche,
    # « pas de place » ne se décoche pas.
    if coute["empiler"]:
        rapport.messages.append(
            f"Empilement interdit par les réglages : {coute['empiler']} colis "
            "de lots pourtant empilables restent à quai. Cochez « Empiler les "
            "colis quand le lot le permet » pour les prendre.")
    if coute["melanger"]:
        rapport.messages.append(
            f"Lots non mélangés : {coute['melanger']} colis restent à quai "
            "faute d'une cale à eux. Cochez « Mélanger les lots dans une même "
            "cale » pour remplir davantage — le chargement sera moins simple.")
    if coute["escales"]:
        rapport.messages.append(
            f"Ordre des escales : {coute['escales']} colis restent à quai "
            "plutôt que d'être empilés sur ce qui se débarque avant.")

    # CE QUE LE PLAN DÉPASSE quand une contrainte est débrayée (D-71) : on
    # relit le plan entier avec les contrôles qu'on n'a pas appliqués, et on
    # le dit cale par cale — chiffres à l'appui, pour que le bord juge.
    if not charge_stricte or not hauteur_stricte:
        rapport.avertissements.extend(
            relire_contraintes(holds, rapport.places,
                               charge=not charge_stricte,
                               hauteur=not hauteur_stricte))

    if poids_courant > 0:
        rapport.lcg_obtenu_m = moment_courant / poids_courant
        rapport.tcg_prevu_m = moment_t_courant / poids_courant

    # Avec quoi chaque cale s'est remplie. Le bord règle une DISPOSITION ; il
    # doit pouvoir vérifier ce que le calepineur en a fait — et, en
    # automatique, lire ce qu'il a choisi tout seul.
    for code, packer in packers.items():
        dite = packer.disposition_employee()
        if dite:
            rapport.disposition_par_cale[code] = dite

    if poids_courant > 0 or poids_hors_cargaison_t > 0:
        # ce qui fait la gîte, c'est le TCG du NAVIRE entier — cargaison et
        # tout le reste — pas celui de la seule cargaison
        rapport.tcg_navire_prevu_m = (
            (moment_t_hors_cargaison_tm + moment_t_courant)
            / (poids_hors_cargaison_t + poids_courant))

    if equilibrage and rapport.tcg_navire_prevu_m is not None:
        reste = rapport.tcg_navire_prevu_m - reglages.tcg_cible_m
        cargo = (f"cargaison à {rapport.tcg_prevu_m:+.2f} m"
                 if rapport.tcg_prevu_m is not None else "sans cargaison")
        if abs(reste) > tolerance_tcg:
            # Un manifeste dissymétrique (une pièce lourde et rien pour lui
            # répondre) ne s'équilibre pas en déplaçant des palettes : on le
            # dit, plutôt que d'annoncer une gîte nulle qui n'existera pas.
            rapport.messages.append(
                f"TCG du navire prévu {rapport.tcg_navire_prevu_m:+.2f} m "
                f"({cargo}) : il reste {reste:+.2f} m à compenser pour "
                f"atteindre {reglages.tcg_cible_m:+.2f} m — le manifeste est "
                "dissymétrique, ou le navire penche trop pour être redressé "
                "par la cargaison. Ballastez, ou déplacez une pièce lourde.")
        else:
            rapport.messages.append(
                f"TCG du navire prévu {rapport.tcg_navire_prevu_m:+.2f} m "
                f"({cargo}) : bâbord et tribord s'équilibrent.")

    # --- vérification : le plan proposé donne-t-il un navire exploitable ?
    # Un solveur qui ne relit pas son propre résultat ne vaut rien : on
    # recalcule l'équilibre du plan et on le dit s'il ne tient pas.
    if navire is not None and poids_courant > 0:
        from . import hydrostatics
        total = poids_hors_cargaison_t + poids_courant
        lcg_total = ((moment_hors_cargaison_tm
                      + moment_courant) / total) if total > 0 else 0.0
        eq = hydrostatics.solve_equilibrium(navire, total, lcg_total)
        rapport.assiette_prevue_m = eq.trim_m
        rapport.dans_domaine = bool(eq.dans_domaine and eq.converged)
        if not rapport.dans_domaine:
            # Accuser l'assiette quoi qu'il arrive envoyait le bord déplacer du
            # poids vers l'avant alors que c'est le tirant d'eau qui sortait de
            # la table (navire trop chargé), ou que le calcul n'avait tout
            # simplement pas convergé. On nomme la grandeur fautive.
            (t_min, t_max), (d_min, d_max) = navire.hydro.bounds()
            hors_assiette = not (t_min - 1e-9 <= eq.trim_m <= t_max + 1e-9)
            hors_tirant = not (d_min - 1e-9 <= eq.draft_m <= d_max + 1e-9)
            fautes = []
            if hors_assiette:
                fautes.append(f"une assiette de {eq.trim_m:+.2f} m, hors du "
                              f"domaine des tables ({t_min:+.2f} à "
                              f"{t_max:+.2f} m)")
            if hors_tirant:
                fautes.append(f"un tirant d'eau de {eq.draft_m:.2f} m, hors du "
                              f"domaine des tables ({d_min:.2f} à "
                              f"{d_max:.2f} m)")
            if fautes:
                quoi = "le plan proposé donne " + " et ".join(fautes) + "."
            else:
                quoi = (f"l'équilibre du plan proposé n'a pas convergé "
                        f"(assiette {eq.trim_m:+.2f} m, tirant d'eau "
                        f"{eq.draft_m:.2f} m).")
            rapport.messages.append(
                f"Attention : {quoi} Le résultat n'est pas exploitable "
                "tel quel — déplacez du poids ou revoyez le manifeste.")
        elif (objectif == ASSIETTE_GM and lcg_cible_cargaison is not None
                and abs(rapport.lcg_obtenu_m - lcg_cible_cargaison) > 0.25):
            rapport.messages.append(
                f"LCG de cargaison obtenu {rapport.lcg_obtenu_m:.2f} m au lieu "
                f"de {lcg_cible_cargaison:.2f} m visé : les cales se "
                "remplissent avant d'atteindre la répartition idéale. "
                f"Assiette prévue {eq.trim_m:+.2f} m.")
        elif objectif == CAPACITE and lcg_cible_cargaison is not None:
            rapport.messages.append(
                f"Assiette prévue par ce plan : {eq.trim_m:+.2f} m — en "
                "objectif capacité, l'assiette ne sert qu'à départager les "
                "cales également libres.")
        else:
            rapport.messages.append(
                f"Assiette prévue par ce plan : {eq.trim_m:+.2f} m.")
    return rapport


def totaux(places, holds):
    """(poids, lcg, tcg, vcg, nb) de l'ensemble des charges placées."""
    holds_par_code = {h.code: h for h in holds}
    w = lm = tm = vm = 0.0
    n = 0
    for code, lst in places.items():
        h = holds_par_code.get(code)
        z = h.z_min if h else 0.0
        for p in lst:
            pw = p.poids_total_t
            cx, cy = p.centre
            w += pw
            lm += pw * cx
            tm += pw * cy
            vm += pw * p.vcg(z)
            n += max(1, p.niveaux)
    if w <= 0:
        return 0.0, 0.0, 0.0, 0.0, 0
    return w, lm / w, tm / w, vm / w, n
