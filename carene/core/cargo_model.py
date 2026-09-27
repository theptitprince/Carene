# -*- coding: utf-8 -*-
"""Charges à embarquer : types réutilisables et placements dans les cales.

Deux notions distinctes :

- un **type de charge** (`CargoType`) décrit un objet qu'on charge souvent :
  une palette Europe, une palette hors normes, un transpalette, un chariot
  élévateur, un colis particulier. Il vit dans le **catalogue** du navire et
  ressert d'un chargement à l'autre ;
- un **placement** (`Placement`) est un exemplaire posé quelque part dans une
  cale, avec sa position, son orientation et son empilement. Il appartient à
  une condition de chargement.

Une charge peut aussi être **ponctuelle** : on saisit ses dimensions et son
poids sans passer par le catalogue (`Placement` avec `type_code` vide).

À part, une troisième notion : le **matériel du bord** (`EquipementBord`,
`InventaireBord`). Un chariot élévateur, un transpalette appartiennent au
NAVIRE et sont là à chaque voyage : ils pèsent et occupent la place, mais ce
n'est pas de la marchandise et ils n'ont pas leur place au manifeste. L'engin
est une donnée du navire (`equipements_bord.json`), sa POSITION une donnée du
point de chargement (un `Placement` portant `equipement_id`).

Trois mesures pour un même colis, à ne jamais confondre (D-39, D-64) :

- l'**emprise** est la palette nominale — c'est elle qui porte le poids, donc
  elle seule qui entre dans la charge au m² ;
- l'**encombrement** est l'emprise plus le **débord** (`debord_m`) de chaque
  côté : ce que le lot prend vraiment quand les sacs sortent de la palette ;
- la **place occupée** (`rect_occupe`) est l'encombrement plus le **jeu
  d'arrimage** de chaque côté. C'est elle qui décide de tout ce qui touche à
  la place, et une place occupée qui en mord une autre est un refus de pose.

Le débord appartient au LOT (au manifeste, ligne par ligne, le type ne fait
que le proposer) ; le **jeu d'arrimage**, lui, est un réglage de travail de la
vue Chargement, commun à TOUS les colis. Le bord le décrit comme « un
débordement d'un colis — typiquement une palette affaissée dont le contenu
dépasse un peu » : c'est donc un débord de plus, de chaque côté de chaque
colis, et non un écart mesuré une fois entre deux voisins. Deux palettes
voisines sont ainsi séparées de 2 × jeu, une palette et la muraille de 1 × jeu
(D-64). Il ne s'écrit dans aucun fichier : ce n'est ni une donnée du navire
ni une donnée du chargement, et les colis posés n'en gardent pas trace.

Ce module ne dépend ni de Qt ni du moteur hydrostatique : il ne connaît que
des rectangles, des poids et des centres de gravité.
"""
from __future__ import annotations
from ..ecriture import ecriture_atomique

import json
import os
import uuid
from dataclasses import dataclass, field

CATALOGUE_FILE = "catalogue_charges.json"
EQUIPEMENTS_FILE = "equipements_bord.json"

# catégories : surtout un repère visuel et un tri pour l'utilisateur
CATEGORIES = ["Palette", "Engin", "Colis", "Autre"]

# Couleur par défaut d'une catégorie. Ce sont des chaînes hexadécimales, pas
# des objets Qt : le plan de cale et la vue iso doivent peindre le même colis
# de la même couleur, et ce module est le seul que les deux partagent.
COULEURS_CATEGORIE = {
    "Palette": "#3E8FB0",
    "Engin": "#C77D3A",
    "Colis": "#7A6CB5",
    "Autre": "#6B8F71",
}


# Palette des lots : douze teintes distinctes, lisibles côte à côte sur un
# plan de cale et dans les deux thèmes. Un nouveau lot en reçoit une d'office,
# et l'officier peut en choisir une autre — « 150 palettes de rhum » et « 200
# de café » doivent se distinguer d'un coup d'œil une fois posées.
PALETTE_LOTS = [
    "#3E8FB0", "#C77D3A", "#6B8F71", "#7A6CB5", "#B0555F", "#4E8A8B",
    "#A8823C", "#5E7CA8", "#8E6BA0", "#5F9455", "#C06A8E", "#7C8B3E",
]


# Le matériel du bord n'est pas de la marchandise : il ne prend pas une teinte
# de la palette des lots, qui sert à distinguer les lots entre eux. Une teinte
# neutre, plus le contour tireté du plan, et on le reconnaît sans lire.
COULEUR_MATERIEL_BORD = "#8C8A93"


def couleur_de_lot(index):
    return PALETTE_LOTS[int(index) % len(PALETTE_LOTS)]


def couleur_hex(p):
    """Couleur d'un placement, d'un type de charge ou d'un matériel du bord."""
    if getattr(p, "couleur", ""):
        return p.couleur
    if getattr(p, "est_materiel_bord", False):
        return COULEUR_MATERIEL_BORD
    return COULEURS_CATEGORIE.get(getattr(p, "categorie", ""),
                                  COULEURS_CATEGORIE["Autre"])


def mention_debord(*colis, jeu=0.0):
    """Ce qu'on ajoute à un refus de pose quand un débord ou le jeu
    d'arrimage y est pour quelque chose : « , débords compris », « , jeu
    d'arrimage compris », ou les deux.

    Un officier à qui l'on refuse une pose alors que les palettes ne se
    touchent visiblement pas doit lire POURQUOI : ce sont les sacs qui se
    touchent, pas les palettes — ou c'est le jeu qu'il a lui-même réglé à la
    molette. Sans débord ni jeu, rien n'est ajouté."""
    d = any(getattr(p, "deborde", False) for p in colis if p is not None)
    j = float(jeu or 0.0) > 1e-9
    if d and j:
        return ", débords et jeu d'arrimage compris"
    if d:
        return ", débords compris"
    if j:
        return ", jeu d'arrimage compris"
    return ""


def rect_occupe(pl, jeu=0.0):
    """(x0, y0, x1, y1) de la PLACE OCCUPÉE : encombrement + jeu d'arrimage.

    Une seule fonction pour toute l'application — plan de chargement, plan de
    cale, aimantation, outil Zone, calepineur. Le jeu n'appartient pas au
    colis (il se règle à la molette et change d'un instant à l'autre) : il ne
    s'écrit donc pas dans `Placement`, il se passe ici au moment où l'on juge
    la place (D-64)."""
    d = max(0.0, getattr(pl, "debord_m", 0.0)) + max(0.0, float(jeu or 0.0))
    dx, dy = pl.emprise
    return (pl.x - d, pl.y - d, pl.x + dx + d, pl.y + dy + d)


def se_touchent(p, q, jeu=0.0, tol=1e-9):
    """Ces deux colis se marchent-ils dessus, débords ET jeu compris ?"""
    ax0, ay0, ax1, ay1 = rect_occupe(p, jeu)
    bx0, by0, bx1, by1 = rect_occupe(q, jeu)
    return (ax0 < bx1 - tol and bx0 < ax1 - tol
            and ay0 < by1 - tol and by0 < ay1 - tol)


@dataclass
class CargoType:
    """Un objet qu'on charge régulièrement, mémorisé dans le catalogue."""

    code: str = ""
    nom: str = ""
    categorie: str = "Palette"
    longueur_m: float = 1.2        # dimension le long de X quand rotation = 0
    largeur_m: float = 0.8         # dimension le long de Y quand rotation = 0
    # Hauteur FACULTATIVE : 0 = non renseignée. La largeur et la longueur d'une
    # palette sont fixées à sa construction, sa hauteur ne l'est pas — elle
    # dépend de ce qu'on empile dessus, donc du chargement. Elle se précise
    # alors lot par lot au manifeste (D-36).
    hauteur_m: float = 1.0
    poids_t: float = 0.5
    # nombre d'exemplaires empilables — le « stack » à l'écran (1 = pas
    # d'empilement) ; le nom d'attribut, lui, reste `gerbable_max` (D-36)
    gerbable_max: int = 1
    rotation_permise: bool = True
    couleur: str = ""              # "" = couleur déduite de la catégorie
    note: str = ""
    # Poids maximal d'un exemplaire (0 = pas de limite). Vient du manuel
    # d'assujettissement : au-delà, la saisie est REFUSÉE, pas signalée (D-8).
    poids_max_t: float = 0.0
    # D'où viennent les chiffres : simple information, jamais une contrainte.
    # Le catalogue appartient à l'utilisateur, pas à sa source (D-36).
    source: str = ""
    # DÉBORD : ce qui dépasse de la palette, de chaque côté (m). Des sacs de
    # café mal empilés sortent de 5 cm tout autour : la palette mesure
    # 1,20 × 0,80, le lot occupe 1,30 × 0,90. Ce n'est pas un réglage de
    # travail (le jeu d'arrimage l'est), c'est la dimension RÉELLE de la
    # marchandise — le type n'en donne qu'une proposition, la vraie valeur se
    # règle lot par lot au manifeste, comme la hauteur et le stack (D-39).
    debord_m: float = 0.0

    @property
    def hauteur_renseignee(self):
        """La hauteur de ce type est-elle connue ?

        Elle sert au contrôle de hauteur libre et au VCG : un 0 ne doit jamais
        entrer dans un calcul. Quand elle manque, c'est le lot du manifeste qui
        la donne, et le dialogue d'ajout l'exige avant d'ajouter."""
        return self.hauteur_m > 0

    def poids_refuse(self, poids_t):
        """Raison de refuser ce poids unitaire, ou None."""
        if self.poids_max_t > 0 and poids_t > self.poids_max_t + 1e-9:
            return (f"{poids_t:g} t dépasse le poids maximal de {self.poids_max_t:g} t "
                    f"fixé pour « {self.nom or self.code} »"
                    + (f" ({self.source})" if self.source else ""))
        return None

    @property
    def emprise_m2(self):
        """Surface de la PALETTE, débord non compris."""
        return self.longueur_m * self.largeur_m

    @property
    def encombrement_m(self):
        """(longueur, largeur) débord compris : la place que le lot prend."""
        d = 2 * max(0.0, self.debord_m)
        return (self.longueur_m + d, self.largeur_m + d)

    @property
    def charge_surfacique_t_m2(self):
        """Pression au sol d'un exemplaire — sert au contrôle de charge de pont.

        Sur l'EMPRISE NOMINALE, jamais sur l'encombrement : le poids passe par
        les pieds de la palette, pas par les sacs qui débordent dans le vide.
        Compter la surface du débord ferait BAISSER la pression annoncée et
        rendrait le contrôle de charge de pont moins sévère qu'il ne doit
        l'être — c'est un point de sécurité (D-39)."""
        a = self.emprise_m2
        return (self.poids_t / a) if a > 0 else 0.0

    def to_dict(self):
        return {
            "code": self.code, "nom": self.nom, "categorie": self.categorie,
            "longueur_m": self.longueur_m, "largeur_m": self.largeur_m,
            "hauteur_m": self.hauteur_m, "poids_t": self.poids_t,
            "gerbable_max": self.gerbable_max,
            "rotation_permise": self.rotation_permise,
            "couleur": self.couleur, "note": self.note,
            "poids_max_t": self.poids_max_t,
            "source": self.source,
            "debord_m": self.debord_m,
        }

    @classmethod
    def from_dict(cls, d):
        # `verrouille` d'un ancien fichier est IGNORÉ, pas repris : plus aucun
        # type n'est verrouillé, le catalogue est à l'utilisateur (D-36).
        return cls(
            code=d.get("code", ""), nom=d.get("nom", ""),
            categorie=d.get("categorie", "Palette"),
            longueur_m=float(d.get("longueur_m", 1.2)),
            largeur_m=float(d.get("largeur_m", 0.8)),
            hauteur_m=float(d.get("hauteur_m", 1.0)),
            poids_t=float(d.get("poids_t", 0.5)),
            gerbable_max=int(d.get("gerbable_max", 1)),
            rotation_permise=bool(d.get("rotation_permise", True)),
            couleur=d.get("couleur", ""), note=d.get("note", ""),
            poids_max_t=float(d.get("poids_max_t", 0.0)),
            source=d.get("source", ""),
            # fichiers d'avant le débord : rien ne dépasse, comme alors
            debord_m=float(d.get("debord_m", 0.0)))


@dataclass
class Placement:
    """Un exemplaire posé dans une cale.

    `x`, `y` sont le coin « bas-gauche » de l'emprise en coordonnées navire
    (X mini, Y mini). `rot` vaut 0 ou 90 degrés. `niveaux` est le nombre
    d'exemplaires empilés à cet endroit — le poids et le centre de gravité en
    découlent.
    """

    type_code: str = ""            # "" pour une charge ponctuelle
    lot_id: str = ""               # ligne de manifeste d'où vient l'exemplaire
    port_dechargement: str = ""    # pour colorer et trier par escale
    nom: str = "Charge"
    longueur_m: float = 1.2
    largeur_m: float = 0.8
    hauteur_m: float = 1.0
    poids_t: float = 0.5
    x: float = 0.0
    y: float = 0.0
    rot: int = 0
    niveaux: int = 1
    epingle: bool = False          # le solveur ne la déplace jamais
    # Matériel du bord : l'identifiant de l'engin dans l'inventaire du navire
    # (`equipements_bord.json`). Non vide = ce n'est pas de la marchandise.
    # La POSITION appartient au point (elle change à chaque escale), l'ENGIN
    # appartient au navire : d'où un identifiant ici et une fiche là-bas.
    equipement_id: str = ""
    categorie: str = "Palette"
    couleur: str = ""
    # Stack propre à la marchandise (1 = interdit d'empiler). Elle suit
    # la charge dans le plan pour que le garde-fou d'empilement s'applique
    # partout, et pas seulement au moment où le solveur répartit.
    gerbable_max: int = 1
    # Rotation interdite par le catalogue ou le manifeste : elle suit la
    # charge dans le plan, pour que la touche R et le tableau la refusent
    # comme le solveur — pas seulement au moment de la répartition.
    rotation_permise: bool = True
    # DÉBORD (m) : ce qui dépasse de la palette, de chaque côté. Recopié de la
    # ligne du manifeste, comme la hauteur — c'est une dimension du LOT, pas
    # un réglage de travail. Il décide de la place occupée (`encombrement`),
    # jamais de la charge au m² (D-39).
    debord_m: float = 0.0
    # La classe IMDG de la marchandise (D-83) — « 3 », « 9 », « 2.1 » — ou ""
    # pour une marchandise ordinaire. Elle suit le colis comme le port : c'est
    # elle que le contrôle de pose confronte à la cale.
    classe_imdg: str = ""

    @property
    def est_materiel_bord(self):
        """Vrai si ce n'est pas de la marchandise mais un engin du navire.

        Le plan le dessine autrement, le manifeste l'ignore, le solveur ne le
        déplace pas et n'empile rien dessus."""
        return bool(self.equipement_id)

    # ------------------------------------------------------------ géométrie
    @property
    def emprise(self):
        """(largeur en X, largeur en Y) une fois l'orientation appliquée."""
        return ((self.largeur_m, self.longueur_m) if self.rot == 90
                else (self.longueur_m, self.largeur_m))

    @property
    def rect(self):
        """(x0, y0, x1, y1) de l'emprise au sol — la palette nominale."""
        dx, dy = self.emprise
        return (self.x, self.y, self.x + dx, self.y + dy)

    @property
    def encombrement(self):
        """(largeur en X, largeur en Y) DÉBORD COMPRIS : la place occupée.

        L'emprise est la palette, l'encombrement est ce que le colis prend
        vraiment : emprise + 2 × débord sur chaque côté. C'est lui qui décide
        de tout ce qui touche à la PLACE — chevauchement, contour de cale,
        obstacles et épontilles, calepinage, aimantation, outil Zone. Jamais
        de la charge au m², qui passe par les pieds de la palette (D-39)."""
        dx, dy = self.emprise
        d = 2 * max(0.0, self.debord_m)
        return (dx + d, dy + d)

    @property
    def rect_encombrement(self):
        """(x0, y0, x1, y1) de la place occupée, débord compris."""
        d = max(0.0, self.debord_m)
        dx, dy = self.encombrement
        return (self.x - d, self.y - d, self.x - d + dx, self.y - d + dy)

    @property
    def deborde(self):
        """Ce colis dépasse-t-il de sa palette ? Sert aux libellés et au
        dessin : un débord nul ne se dit ni ne se trace."""
        return self.debord_m > 1e-9

    @property
    def centre(self):
        dx, dy = self.emprise
        return (self.x + dx / 2, self.y + dy / 2)

    @property
    def poids_total_t(self):
        return self.poids_t * max(1, self.niveaux)

    @property
    def hauteur_totale_m(self):
        return self.hauteur_m * max(1, self.niveaux)

    def vcg(self, z_plancher):
        return z_plancher + self.hauteur_totale_m / 2

    def niveaux_max(self, hauteur_utile_m=0.0):
        """Empilement maximal admissible à cet endroit.

        Deux limites, la plus contraignante l'emporte : ce que la marchandise
        supporte (`gerbable_max`) et ce que la hauteur libre de la cale
        autorise. Le résultat ne descend jamais sous 1 : une charge trop haute
        pour la cale reste posée, mais elle est signalée comme problème — on ne
        la fait pas disparaître silencieusement.
        """
        n = max(1, int(self.gerbable_max or 1))
        if hauteur_utile_m > 0 and self.hauteur_m > 0:
            n = min(n, int(hauteur_utile_m / self.hauteur_m + 1e-9))
        return max(1, n)

    def charge_surfacique_t_m2(self):
        """Pression au sol de la pile, sur l'EMPRISE NOMINALE.

        Le débord n'entre pas dans ce calcul : le poids descend par les pieds
        de la palette, pas par les sacs qui dépassent dans le vide. Diviser
        par l'encombrement donnerait une pression plus faible que la vraie et
        laisserait passer une charge que le pont ne supporte pas — c'est le
        point de sécurité de D-39."""
        dx, dy = self.emprise
        a = dx * dy
        return (self.poids_total_t / a) if a > 0 else 0.0

    def chevauche(self, autre, tol=1e-9, jeu=0.0):
        """Ces deux colis se marchent-ils dessus, débords et jeu compris ?

        Deux palettes dont les sacs se touchent, c'est un refus au même titre
        que deux palettes qui se chevauchent (D-27, D-39) : la place occupée
        est l'encombrement, pas la palette — et le jeu d'arrimage s'y ajoute
        quand l'appelant en a un à faire respecter (D-64)."""
        return se_touchent(self, autre, jeu, tol)

    # ------------------------------------------------------------ fichiers
    def to_dict(self):
        return {
            "type_code": self.type_code, "nom": self.nom,
            "lot_id": self.lot_id,
            "longueur_m": self.longueur_m, "largeur_m": self.largeur_m,
            "hauteur_m": self.hauteur_m, "poids_t": self.poids_t,
            "x": self.x, "y": self.y, "rot": self.rot,
            "niveaux": self.niveaux, "epingle": self.epingle,
            "equipement_id": self.equipement_id,
            "categorie": self.categorie, "couleur": self.couleur,
            "gerbable_max": self.gerbable_max,
            "port_dechargement": self.port_dechargement,
            "rotation_permise": self.rotation_permise,
            "debord_m": self.debord_m,
            **({"classe_imdg": self.classe_imdg} if self.classe_imdg else {}),
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            classe_imdg=str(d.get("classe_imdg", "") or ""),
            type_code=d.get("type_code", ""), nom=d.get("nom", "Charge"),
            lot_id=d.get("lot_id", ""),
            port_dechargement=d.get("port_dechargement", ""),
            longueur_m=float(d.get("longueur_m", 1.2)),
            largeur_m=float(d.get("largeur_m", 0.8)),
            hauteur_m=float(d.get("hauteur_m", 1.0)),
            poids_t=float(d.get("poids_t", 0.5)),
            x=float(d.get("x", 0.0)), y=float(d.get("y", 0.0)),
            rot=int(d.get("rot", 0)), niveaux=int(d.get("niveaux", 1)),
            epingle=bool(d.get("epingle", False)),
            equipement_id=d.get("equipement_id", ""),
            categorie=d.get("categorie", "Palette"),
            couleur=d.get("couleur", ""),
            # cas enregistré avant l'ajout du champ : on ne rabaisse pas un
            # empilement déjà validé par l'officier, on le prend pour limite
            gerbable_max=int(d.get("gerbable_max",
                                   max(1, int(d.get("niveaux", 1))))),
            # fichiers d'avant le champ : rotation libre, comme alors
            rotation_permise=bool(d.get("rotation_permise", True)),
            # fichiers d'avant le débord : rien ne dépasse, comme alors
            debord_m=float(d.get("debord_m", 0.0)))

    @classmethod
    def from_type(cls, t: CargoType, x=0.0, y=0.0, rot=0, niveaux=1, nom=None,
                  hauteur_m=None, gerbable_max=None, debord_m=None):
        """Un exemplaire de ce type, posé.

        La hauteur du catalogue est facultative (0 = non renseignée) : celle du
        colis posé se donne alors ici. Elle n'est jamais laissée à 0 — elle
        entre dans la hauteur libre et dans le VCG, et un zéro y ferait une
        pile de hauteur nulle passant sous tous les contrôles."""
        h = t.hauteur_m if hauteur_m is None else float(hauteur_m)
        if h <= 0:
            raise ValueError(
                f"Hauteur non renseignée pour « {t.nom or t.code} » : "
                "elle sert au contrôle de hauteur libre et au centre de "
                "gravité, elle doit être donnée avant de poser.")
        return cls(type_code=t.code, nom=nom or t.nom or t.code,
                   longueur_m=t.longueur_m, largeur_m=t.largeur_m,
                   hauteur_m=h, poids_t=t.poids_t,
                   x=x, y=y, rot=rot, niveaux=niveaux,
                   categorie=t.categorie, couleur=t.couleur,
                   gerbable_max=(t.gerbable_max if gerbable_max is None
                                 else max(1, int(gerbable_max))),
                   debord_m=(t.debord_m if debord_m is None
                             else max(0.0, float(debord_m))),
                   rotation_permise=t.rotation_permise)


@dataclass
class ManifestLine:
    """Une ligne du manifeste : ce qu'il y a à embarquer, et en quelle quantité."""

    type_code: str = ""
    nom: str = "Charge"
    quantite: int = 1
    # dimensions recopiées : une charge ponctuelle n'est dans aucun catalogue,
    # et un type peut être modifié après coup sans réécrire l'historique
    longueur_m: float = 1.2
    largeur_m: float = 0.8
    hauteur_m: float = 1.0
    poids_t: float = 0.5
    gerbable_max: int = 1
    rotation_permise: bool = True
    # DÉBORD (m) : ce qui dépasse de la palette, de chaque côté, pour CE lot.
    # Comme la hauteur et le stack, c'est une dimension du lot et non du type
    # (D-36, D-39) : la même palette EUR porte des fûts au carré ou des sacs
    # de café qui sortent de 5 cm. Le type ne fait que le proposer.
    debord_m: float = 0.0
    categorie: str = "Palette"
    couleur: str = ""
    cale_imposee: str = ""         # "" = le solveur choisit
    classe_imdg: str = ""          # classe IMDG, "" = marchandise ordinaire (D-83)
    port_chargement: str = ""      # escale où l'on embarque
    port_dechargement: str = ""    # escale où l'on débarque
    note: str = ""
    # Charge propre au navire : encombrante et posée en cale, mais qui n'est
    # pas de la marchandise à embarquer — gréement de rechange, matériel de
    # saisine, engin du bord. Elle occupe la place et pèse, elle ne se compte
    # pas au manifeste et le solveur n'a pas à la répartir.
    hors_manifeste: bool = False
    # Identité stable de la LIGNE, pas du type : « 150 palettes de rhum » et
    # « 200 palettes de café » sont deux lots du même type EUR. C'est par elle
    # qu'on rattache un colis posé à sa ligne — pour le compte du manifeste
    # comme pour la couleur sur le plan.
    lot_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    @property
    def poids_total_t(self):
        return self.poids_t * self.quantite

    def to_dict(self):
        return {
            "type_code": self.type_code, "nom": self.nom,
            "quantite": self.quantite,
            "longueur_m": self.longueur_m, "largeur_m": self.largeur_m,
            "hauteur_m": self.hauteur_m, "poids_t": self.poids_t,
            "gerbable_max": self.gerbable_max,
            "rotation_permise": self.rotation_permise,
            "debord_m": self.debord_m,
            "categorie": self.categorie, "couleur": self.couleur,
            "cale_imposee": self.cale_imposee,
            "port_chargement": self.port_chargement,
            "port_dechargement": self.port_dechargement,
            "note": self.note, "lot_id": self.lot_id,
            "hors_manifeste": self.hors_manifeste,
            **({"classe_imdg": self.classe_imdg} if self.classe_imdg else {}),
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            type_code=d.get("type_code", ""), nom=d.get("nom", "Charge"),
            quantite=int(d.get("quantite", 1)),
            longueur_m=float(d.get("longueur_m", 1.2)),
            largeur_m=float(d.get("largeur_m", 0.8)),
            hauteur_m=float(d.get("hauteur_m", 1.0)),
            poids_t=float(d.get("poids_t", 0.5)),
            gerbable_max=int(d.get("gerbable_max", 1)),
            rotation_permise=bool(d.get("rotation_permise", True)),
            # fichiers d'avant le débord : rien ne dépasse, comme alors
            debord_m=float(d.get("debord_m", 0.0)),
            categorie=d.get("categorie", "Palette"),
            couleur=d.get("couleur", ""),
            cale_imposee=d.get("cale_imposee", ""),
            port_chargement=d.get("port_chargement", ""),
            port_dechargement=d.get("port_dechargement", ""),
            note=d.get("note", ""),
            lot_id=d.get("lot_id") or uuid.uuid4().hex[:8],
            hors_manifeste=bool(d.get("hors_manifeste", False)),
            classe_imdg=str(d.get("classe_imdg", "") or ""))

    @classmethod
    def from_type(cls, t: CargoType, quantite=1, hauteur_m=None,
                  gerbable_max=None, debord_m=None):
        """Un lot de ce type.

        La HAUTEUR, le GERBAGE et le DÉBORD appartiennent au lot, pas au
        type : la largeur d'une palette est donnée à sa construction, mais ce
        qu'on empile dessus décide de sa hauteur, de sa gerbabilité et de ce
        qui dépasse (D-36, D-39). Le type ne fournit qu'une proposition ;
        quand il n'en a pas (hauteur 0 = non renseignée), la valeur est exigée
        ici."""
        h = t.hauteur_m if hauteur_m is None else float(hauteur_m)
        if h <= 0:
            raise ValueError(
                f"Hauteur non renseignée pour « {t.nom or t.code} » : "
                "elle sert au contrôle de hauteur libre et au centre de "
                "gravité, elle doit être donnée sur la ligne du manifeste.")
        return cls(type_code=t.code, nom=t.nom or t.code, quantite=quantite,
                   longueur_m=t.longueur_m, largeur_m=t.largeur_m,
                   hauteur_m=h, poids_t=t.poids_t,
                   gerbable_max=(t.gerbable_max if gerbable_max is None
                                 else max(1, int(gerbable_max))),
                   debord_m=(t.debord_m if debord_m is None
                             else max(0.0, float(debord_m))),
                   rotation_permise=t.rotation_permise,
                   categorie=t.categorie, couleur=t.couleur)

    def to_placement(self, nom=None):
        return Placement(
            type_code=self.type_code, nom=nom or self.nom, lot_id=self.lot_id,
            longueur_m=self.longueur_m, largeur_m=self.largeur_m,
            hauteur_m=self.hauteur_m, poids_t=self.poids_t,
            categorie=self.categorie, couleur=self.couleur,
            gerbable_max=self.gerbable_max,
            debord_m=self.debord_m,
            rotation_permise=self.rotation_permise,
            port_dechargement=self.port_dechargement,
            classe_imdg=self.classe_imdg)


# ------------------------------------------------------------------ catalogue
DEFAUT_CATALOGUE = [
    CargoType(code="EUR", nom="Palette Europe 1200x800", categorie="Palette",
              longueur_m=1.2, largeur_m=0.8, hauteur_m=1.0, poids_t=0.6,
              gerbable_max=3, rotation_permise=True),
    CargoType(code="ISO", nom="Palette ISO 1200x1000", categorie="Palette",
              longueur_m=1.2, largeur_m=1.0, hauteur_m=1.0, poids_t=0.8,
              gerbable_max=3, rotation_permise=True),
    CargoType(code="DEMI", nom="Demi-palette 800x600", categorie="Palette",
              longueur_m=0.8, largeur_m=0.6, hauteur_m=0.9, poids_t=0.3,
              gerbable_max=3, rotation_permise=True),
    CargoType(code="TRANSPAL", nom="Transpalette", categorie="Engin",
              longueur_m=1.6, largeur_m=0.7, hauteur_m=1.3, poids_t=0.12,
              gerbable_max=1, rotation_permise=True),
    CargoType(code="CHARIOT", nom="Chariot élévateur", categorie="Engin",
              longueur_m=3.0, largeur_m=1.2, hauteur_m=2.2, poids_t=2.5,
              gerbable_max=1, rotation_permise=True),
]


class Catalogue:
    """Les types de charges du bord, enregistrés avec le navire."""

    def __init__(self, types=None):
        self.types = list(types) if types else []
        # avertissements de chargement (fichier illisible mis de côté…),
        # à afficher par l'interface
        self.messages = []

    def __len__(self):
        return len(self.types)

    def __iter__(self):
        return iter(self.types)

    def get(self, code):
        return next((t for t in self.types if t.code == code), None)

    def add(self, t: CargoType):
        """Ajoute ou remplace le type de même code. Retourne le type retenu."""
        existing = self.get(t.code)
        if existing is not None:
            self.types[self.types.index(existing)] = t
        else:
            self.types.append(t)
        return t

    def remove(self, code):
        """Retire le type. Rien n'est protégé : le catalogue est celui de
        l'utilisateur, quelle que soit la source des chiffres (D-36)."""
        t = self.get(code)
        if t is not None:
            self.types.remove(t)
            return t
        return None

    def unique_code(self, base):
        """Code libre dérivé de `base` (les codes identifient les types)."""
        base = (base or "TYPE").strip().upper().replace(" ", "_") or "TYPE"
        if self.get(base) is None:
            return base
        i = 2
        while self.get(f"{base}_{i}") is not None:
            i += 1
        return f"{base}_{i}"

    # ------------------------------------------------------------ fichiers
    def to_dict(self):
        return {"format": "carene-catalogue", "version": 1,
                "types": [t.to_dict() for t in self.types]}

    @classmethod
    def from_dict(cls, d):
        return cls([CargoType.from_dict(t) for t in (d or {}).get("types", [])])

    def save(self, ship_folder):
        path = os.path.join(ship_folder, CATALOGUE_FILE)
        os.makedirs(ship_folder, exist_ok=True)
        with ecriture_atomique(path) as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=1)
        return path

    @classmethod
    def load(cls, ship_folder, defauts=True):
        """Catalogue du navire ; à défaut, un jeu de types courants."""
        path = os.path.join(ship_folder, CATALOGUE_FILE)
        messages = []
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return cls.from_dict(json.load(f))
            except (OSError, ValueError, TypeError, KeyError) as e:
                # Un fichier illisible n'est pas écrasé en silence par le
                # prochain enregistrement du catalogue par défaut : on le met
                # de côté (<nom>.bad) pour qu'il reste récupérable à la main.
                bad = path + ".bad"
                try:
                    if os.path.exists(bad):
                        os.remove(bad)
                    os.replace(path, bad)
                    messages.append(
                        f"Catalogue « {CATALOGUE_FILE} » illisible ({e}) : "
                        f"mis de côté sous « {os.path.basename(bad)} », "
                        "catalogue par défaut chargé à la place.")
                except OSError as e2:
                    messages.append(
                        f"Catalogue « {CATALOGUE_FILE} » illisible ({e}) et "
                        f"impossible à mettre de côté ({e2}) : catalogue par "
                        "défaut chargé, le fichier sera écrasé au prochain "
                        "enregistrement.")
        cat = cls([CargoType.from_dict(t.to_dict()) for t in DEFAUT_CATALOGUE]
                  if defauts else [])
        cat.messages = messages
        return cat


# ------------------------------------------------------ matériel du bord
@dataclass
class EquipementBord:
    """Un engin qui appartient au NAVIRE, pas au voyage.

    Un chariot élévateur ou un transpalette servent au chargement : ils sont
    à bord à chaque voyage, ils pèsent et ils occupent la place, mais ils
    n'ont rien à faire au manifeste — le manifeste dit ce qui attend sur le
    quai (D-20), et personne ne débarque le chariot du bord.

    Ce qui appartient au navire est ici (l'engin, ses dimensions, son poids,
    s'il est à bord) et vit dans `equipements_bord.json` du dossier du navire,
    à côté du catalogue. Ce qui appartient au point de chargement — **où** il
    est arrimé — reste dans les `placements` de la condition : ça change à
    chaque escale et ça doit s'archiver avec le point.
    """

    id: str = ""
    nom: str = "Matériel du bord"
    categorie: str = "Engin"
    longueur_m: float = 1.0
    largeur_m: float = 1.0
    hauteur_m: float = 1.0
    poids_t: float = 0.0
    # 1 = rien ne s'empile dessus. Le solveur, lui, n'y empile jamais rien
    # quoi qu'il arrive : c'est un obstacle, pas une pile à garnir.
    gerbable_max: int = 1
    rotation_permise: bool = True
    couleur: str = ""              # "" = teinte neutre du matériel du bord
    note: str = ""
    # À bord ou non : un engin débarqué pour révision reste à l'inventaire du
    # navire, il ne pèse simplement plus. Le retirer du PLAN ne le retire pas
    # de l'inventaire — il est toujours à bord, seulement pas encore arrimé.
    a_bord: bool = True
    source: str = ""               # d'où viennent les chiffres
    # Chiffre non sourcé, à faire confirmer par le bord : on préfère le dire
    # qu'inventer une dimension qui finirait par servir à un calage.
    a_confirmer: bool = False
    # Combien d'exemplaires IDENTIQUES le navire en porte. Un armement a
    # rarement un seul transpalette ; les compter séparément obligerait à
    # créer une fiche par engin là où c'est le même matériel, au même poids et
    # aux mêmes dimensions. Deux engins qui n'ont PAS la même prescription
    # d'arrimage restent, eux, deux fiches (D-37).
    quantite: int = 1

    @property
    def est_materiel_bord(self):
        return True

    @property
    def poids_total_t(self):
        """Ce que cet engin pèse à bord : tous ses exemplaires."""
        return self.poids_t * max(1, int(self.quantite or 1))

    def to_dict(self):
        return {
            "id": self.id, "nom": self.nom, "categorie": self.categorie,
            "longueur_m": self.longueur_m, "largeur_m": self.largeur_m,
            "hauteur_m": self.hauteur_m, "poids_t": self.poids_t,
            "quantite": self.quantite,
            "gerbable_max": self.gerbable_max,
            "rotation_permise": self.rotation_permise,
            "couleur": self.couleur, "note": self.note,
            "a_bord": self.a_bord, "source": self.source,
            "a_confirmer": self.a_confirmer,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            id=d.get("id") or uuid.uuid4().hex[:8],
            nom=d.get("nom", "Matériel du bord"),
            categorie=d.get("categorie", "Engin"),
            longueur_m=float(d.get("longueur_m", 1.0)),
            largeur_m=float(d.get("largeur_m", 1.0)),
            hauteur_m=float(d.get("hauteur_m", 1.0)),
            poids_t=float(d.get("poids_t", 0.0)),
            # fichiers d'avant le champ : un exemplaire, comme alors
            quantite=max(1, int(d.get("quantite", 1) or 1)),
            gerbable_max=int(d.get("gerbable_max", 1)),
            rotation_permise=bool(d.get("rotation_permise", True)),
            couleur=d.get("couleur", ""), note=d.get("note", ""),
            a_bord=bool(d.get("a_bord", True)),
            source=d.get("source", ""),
            a_confirmer=bool(d.get("a_confirmer", False)))

    def to_placement(self, x=0.0, y=0.0, rot=0):
        """L'engin arrimé quelque part : c'est un `Placement` comme un autre.

        Même objet que pour la marchandise, donc mêmes accrochages, mêmes
        contrôles de contenance (D-27), même poids dans le bilan et la
        stabilité. Seul `equipement_id` le distingue — et il suffit."""
        return Placement(
            type_code="", lot_id="", equipement_id=self.id, nom=self.nom,
            longueur_m=self.longueur_m, largeur_m=self.largeur_m,
            hauteur_m=self.hauteur_m, poids_t=self.poids_t,
            x=x, y=y, rot=rot, niveaux=1,
            # ÉPINGLÉ d'office : c'est ainsi qu'une charge dit « le solveur ne
            # me touche pas » partout dans le logiciel, y compris dans le plan
            # de cale. La main de l'officier, elle, le déplace quand même — un
            # chariot s'arrime où le bord décide (D-17).
            epingle=True,
            categorie=self.categorie,
            couleur=self.couleur or COULEUR_MATERIEL_BORD,
            gerbable_max=max(1, int(self.gerbable_max or 1)),
            rotation_permise=self.rotation_permise)


class InventaireBord:
    """Le matériel du bord d'un navire, enregistré dans son dossier.

    Même esprit que le catalogue des charges : c'est une donnée du navire,
    pas du code. Un navire sans fichier a un inventaire VIDE — on n'invente
    pas d'engin au nom d'un armement qu'on ne connaît pas."""

    def __init__(self, items=None):
        self.items = list(items) if items else []
        self.messages = []          # avertissements de chargement

    def __len__(self):
        return len(self.items)

    def __iter__(self):
        return iter(self.items)

    def get(self, eid):
        return next((e for e in self.items if e.id == eid), None)

    def a_bord(self):
        return [e for e in self.items if e.a_bord]

    def add(self, e: EquipementBord):
        """Ajoute ou remplace l'engin de même id. Retourne l'engin retenu."""
        if not e.id:
            e.id = self.unique_id(e.nom)
        existant = self.get(e.id)
        if existant is not None:
            self.items[self.items.index(existant)] = e
        else:
            self.items.append(e)
        return e

    def remove(self, eid):
        e = self.get(eid)
        if e is not None:
            self.items.remove(e)
        return e

    def unique_id(self, base):
        base = "".join(c for c in (base or "MB").strip().upper().replace(" ", "_")
                       if c.isalnum() or c == "_") or "MB"
        if self.get(base) is None:
            return base
        i = 2
        while self.get(f"{base}_{i}") is not None:
            i += 1
        return f"{base}_{i}"

    # ------------------------------------------------------------ fichiers
    def to_dict(self):
        return {"format": "carene-equipements-bord", "version": 1,
                "equipements": [e.to_dict() for e in self.items]}

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        return cls([EquipementBord.from_dict(e)
                    for e in (d.get("equipements") or [])])

    def save(self, ship_folder):
        path = os.path.join(ship_folder, EQUIPEMENTS_FILE)
        os.makedirs(ship_folder, exist_ok=True)
        with ecriture_atomique(path) as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=1)
        return path

    @classmethod
    def load(cls, ship_folder):
        """L'inventaire du navire ; à défaut, un inventaire vide.

        Un fichier illisible n'est pas écrasé en silence au prochain
        enregistrement : il est mis de côté (`.bad`), comme le catalogue."""
        path = os.path.join(ship_folder or "", EQUIPEMENTS_FILE)
        inv = cls()
        if not os.path.exists(path):
            return inv
        try:
            with open(path, encoding="utf-8") as f:
                inv = cls.from_dict(json.load(f))
            return inv
        except (OSError, ValueError, TypeError, KeyError) as e:
            bad = path + ".bad"
            inv = cls()
            try:
                if os.path.exists(bad):
                    os.remove(bad)
                os.replace(path, bad)
                inv.messages.append(
                    f"Matériel du bord « {EQUIPEMENTS_FILE} » illisible ({e}) : "
                    f"mis de côté sous « {os.path.basename(bad)} », "
                    "inventaire vide chargé à la place.")
            except OSError as e2:
                inv.messages.append(
                    f"Matériel du bord « {EQUIPEMENTS_FILE} » illisible ({e}) "
                    f"et impossible à mettre de côté ({e2}).")
            return inv
