# -*- coding: utf-8 -*-
"""Le journal du navire : une suite chronologique de **points**.

Un point est l'état complet du navire à un instant — soutes relevées,
charges posées, manifeste, poids divers — avec la date, le lieu et un libellé
choisi (« Arrivée », « Départ », ou autre chose). Il porte aussi, quand la
compagnie en donne un, le **numéro de voyage** de l'armement — celui des
papiers du bord ; l'identifiant du point, lui, reste son numéro. Les points
n'ont pas de type : on en crée un quand on en a besoin.

Un point porte **deux dates**, et les confondre était une gêne quotidienne :
la **date du point** (`horodatage`) est celle de l'événement — l'arrivée, le
départ, le relevé en mer — saisie par le bord ; la **date de modification**
(`modifie_le`) est celle du dernier enregistrement du fichier, posée toute
seule par `Journal.enregistrer`.

Deux règles, et elles font tout le modèle :

- **un point est figé ou en cours.** Figé, il n'est plus jamais réécrit : c'est
  l'archive de ce qu'était le navire à ce moment-là, verdict compris. En
  cours, on y travaille librement ;
- **un nouveau point est la copie intégrale du précédent.** Rien ne se perd :
  on part de ce qu'on avait et on modifie ce qui a changé.

Les cas de chargement d'autrefois (`conditions/`) ne disparaissent pas : ils
s'importent comme point.

Pas de Qt ici. Un point = un fichier `journal/NNNN.json` dans le dossier du
navire ; le fichier d'un point figé porte `"fige": true` et n'est plus écrit.
"""
from __future__ import annotations
from .ecriture import ecriture_atomique, lire_json_ou_bak

import copy
import json
import os
import time
from dataclasses import dataclass, field

from .condition_model import (
    LoadingCondition, compter_colis, lisible, maintenant, poids_pose_t)

JOURNAL_DIR = "journal"
FORMAT = "carene-point"


# Libellés usuels d'un point : la liste est ouverte (on peut taper autre
# chose), mais neuf points sur dix sont l'un de ceux-là, et les proposer évite
# qu'un même moment s'appelle « Depart », « départ » puis « DEP » selon le jour.
LIBELLES = [
    "Arrivée", "Début de chargement", "Fin de chargement",
    "Début de déchargement", "Fin de déchargement", "Départ",
    "Après soutage", "Après ballastage", "Passage en mer", "Avant entrée au port",
]
# Les deux moments de tête : sur une escale ordinaire, un point est une
# arrivée ou un départ, et rien d'autre. Ils se choisissent donc d'un geste,
# sans dérouler la liste complète ; tout le reste se prend sous « Autre… ».
LIBELLES_PHARES = ["Arrivée", "Départ"]
# L'entrée du menu qui ouvre le texte libre (et, avec lui, la liste complète
# ci-dessus). Ce n'est jamais un libellé enregistré : c'est un choix de menu.
AUTRE = "Autre…"


def libelles_autres():
    """Les libellés de la liste qui ne sont pas les deux moments de tête —
    ce que propose le champ libre quand on a choisi « Autre… »."""
    return [l for l in LIBELLES if l not in LIBELLES_PHARES]


# Nature du lieu : un port nommé, ou la mer.
EN_MER = "En mer"


@dataclass
class Point:
    """Un état complet, daté et situé.

    **Deux dates, et elles ne disent pas la même chose.** `horodatage` est la
    date DU POINT — l'événement : l'heure de l'arrivée, du départ, du relevé en
    mer. Elle est saisie par le bord, elle se corrige, et c'est elle qu'on lit
    dans le journal des années plus tard. `modifie_le` est la date du DERNIER
    ENREGISTREMENT du fichier : elle ne se saisit jamais, `Journal.enregistrer`
    la pose. Confondre les deux, c'est ne plus savoir si un point « du 3 mars »
    a été retouché le 12.
    """

    numero: int = 1
    horodatage: str = field(default_factory=maintenant)
    # posée par `Journal.enregistrer` / `figer`, jamais par l'officier. Vide
    # tant que le point n'a pas été enregistré — et vide aussi sur les points
    # écrits avant que cette date existe, qui l'affichent « — ».
    modifie_le: str = ""
    lieu: str = ""                  # port, mouillage, « en mer »
    libelle: str = ""               # « Départ Le Havre », « après soutage »…
    # Le numéro de voyage de la compagnie : celui qui figure sur les papiers
    # de l'armement, pas le nôtre. Le numéro du point reste l'identifiant du
    # journal ; celui-ci ne sert qu'à retrouver le point dans les documents
    # du bord. On ne l'invente jamais : vide, il reste vide.
    voyage: str = ""
    note: str = ""
    fige: bool = False
    condition: LoadingCondition = field(default_factory=LoadingCondition)
    # instantané des résultats au moment où le point a été figé : ce qui a été
    # lu à l'écran ce jour-là, avec la version du moteur qui l'a calculé. Il
    # sert à la liste du journal ; à l'ouverture, tout est recalculé.
    resultats: dict | None = None
    path: str = ""

    # ------------------------------------------------------------- affichage
    @property
    def date_lisible(self) -> str:
        """La date DU POINT : l'événement, celle que le bord a saisie."""
        return lisible(self.horodatage)

    @property
    def modifie_lisible(self) -> str:
        """La date du dernier enregistrement — « — » s'il n'y en a pas."""
        return lisible(self.modifie_le)

    @property
    def titre(self) -> str:
        parts = [f"Point {self.numero}"]
        if self.libelle:
            parts.append(self.libelle)
        elif self.lieu:
            parts.append(self.lieu)
        return " · ".join(parts)

    @property
    def etat(self) -> str:
        return "figé" if self.fige else "en cours"

    @property
    def poids_cargaison_t(self) -> float:
        """Le poids de la cargaison seule : la somme des charges posées.

        Ni les soutes, ni le lège, ni les poids divers — c'est ce que le bord
        appelle « la cargaison », et c'est ce qu'on compare d'un point au
        suivant. Ce n'est pas un résultat de calcul mais un inventaire : les
        charges posées sont dans le point lui-même, donc le chiffre reste
        exact même pour un point figé, relu du disque des années plus tard.
        """
        return poids_pose_t(self.condition.placements)

    @property
    def nb_colis_poses(self) -> int:
        """Les colis posés dans les cales, empilement compris — de quoi juger
        d'un coup d'œil, dans une liste de points, si celui-ci est chargé."""
        return compter_colis(self.condition.placements)

    # ------------------------------------------------------------- fichiers
    def to_dict(self):
        d = {
            "format": FORMAT, "version": 1,
            "numero": self.numero, "horodatage": self.horodatage,
            "lieu": self.lieu, "libelle": self.libelle, "voyage": self.voyage,
            "note": self.note,
            "fige": self.fige,
            "condition": self.condition.to_dict(),
            "resultats": self.resultats,
        }
        # ABSENTE tant que le point n'a jamais été enregistré : le fichier ne
        # doit pas prétendre à une date de modification qui n'existe pas
        if self.modifie_le:
            d["modifie_le"] = self.modifie_le
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(
            numero=int(d.get("numero", 1)),
            horodatage=d.get("horodatage", ""),
            # absente des points écrits avant les deux dates : vide, donc « — »
            # — et surtout pas l'horodatage recopié, qui ferait croire que le
            # point a été enregistré le jour de l'événement
            modifie_le=str(d.get("modifie_le", "") or ""),
            lieu=d.get("lieu", ""), libelle=d.get("libelle", ""),
            # un point écrit avant que le voyage existe n'en a pas : vide,
            # et surtout pas deviné à partir du lieu ou de la date
            voyage=str(d.get("voyage", "") or ""),
            note=d.get("note", ""), fige=bool(d.get("fige", False)),
            condition=LoadingCondition.from_dict(d.get("condition") or {}),
            # copié, pas partagé : le dictionnaire d'origine peut être celui
            # que le journal garde en mémoire (voir `Journal.points`)
            resultats=(dict(d["resultats"])
                       if isinstance(d.get("resultats"), dict) else d.get("resultats")),
        )

    @classmethod
    def load(cls, path: str) -> "Point":
        # un fichier abîmé (coupure pendant l'écriture d'une version d'avant
        # l'écriture protégée) est relu dans sa copie .bak (D-77)
        d, _source = lire_json_ou_bak(path)
        if d.get("format") != FORMAT:
            raise ValueError("Ce fichier n'est pas un point du journal.")
        p = cls.from_dict(d)
        p.path = path
        return p

    def copie(self) -> "Point":
        """Un nouveau point en cours, copie intégrale de celui-ci — datation,
        lieu et libellé à redonner, résultats à recalculer.

        Le numéro de voyage, lui, est **repris** : un voyage porte plusieurs
        points (arrivée, chargement, départ), et le retaper à chaque point
        serait la meilleure façon de se tromper d'un chiffre en route.

        La date de modification, elle, repart à vide : ce point-ci n'a jamais
        été enregistré, et hériter de celle du précédent serait un mensonge."""
        return Point(numero=self.numero + 1, horodatage=maintenant(),
                     modifie_le="",
                     lieu=self.lieu, libelle="", voyage=self.voyage,
                     note="", fige=False,
                     condition=copy.deepcopy(self.condition), resultats=None)


class PointFige(Exception):
    """On a voulu réécrire un point figé."""


class Journal:
    """Les points d'un navire, rangés dans `journal/` de son dossier."""

    def __init__(self, ship_folder: str):
        self.folder = ship_folder
        self.dir = os.path.join(ship_folder, JOURNAL_DIR)
        # Mémoire des points lus : (empreinte du dossier, [dict de chaque
        # point]). L'interface appelle `points()` quatre fois par recalcul
        # (lieux, voyages, liste du journal, choix du point), et un recalcul
        # part à chaque colis posé : sans mémoire, poser une charge relisait
        # et reparsait tout le journal quatre fois de suite.
        self._memo = None

    # ------------------------------------------------------------- lecture
    def chemins(self):
        if not os.path.isdir(self.dir):
            return []
        return sorted(os.path.join(self.dir, fn) for fn in os.listdir(self.dir)
                      if fn.endswith(".json"))

    def _empreinte(self):
        """(nom de fichier, mtime, taille) de chaque point du dossier.

        C'est la clé de la mémoire : un fichier réécrit, ajouté ou supprimé la
        change, y compris par une autre fenêtre ou à la main. On invalide
        malgré tout explicitement à chaque écriture d'ici — deux écritures dans
        la même seconde peuvent produire la même empreinte sur un système de
        fichiers à faible résolution d'horodatage."""
        emp = []
        for path in self.chemins():
            try:
                st = os.stat(path)
            except OSError:
                continue
            emp.append((os.path.basename(path), st.st_mtime_ns, st.st_size))
        return tuple(emp)

    def oublier(self):
        """Oublie les points mémorisés : le prochain `points()` relit le
        dossier. À appeler dès qu'on écrit dans `journal/`."""
        self._memo = None

    def _lus(self):
        """[(chemin, dict)] des points du dossier, relus seulement si le
        dossier a changé. C'est la mémoire elle-même ; tout le reste s'en
        déduit."""
        emp = self._empreinte()
        if self._memo is None or self._memo[0] != emp:
            brut = []
            # UN POINT ABÎMÉ NE DISPARAÎT PLUS EN SILENCE (D-77). Il sautait
            # de la liste, son numéro devenait inutilisable (« point figé »),
            # et rien ne le disait. On le relit dans sa copie .bak s'il en a
            # une ; sinon on le nomme. La vue Journal et l'ouverture du navire
            # lisent `restaures` et `illisibles`.
            self.restaures, self.illisibles = [], []
            for path in self.chemins():
                try:
                    d, source = lire_json_ou_bak(path)
                    if d.get("format") != FORMAT:
                        raise ValueError("Ce fichier n'est pas un point du journal.")
                except (OSError, ValueError):
                    self.illisibles.append(path)
                    continue
                if source == "bak":
                    self.restaures.append(path)
                brut.append((path, d))
            self._memo = (emp, brut)
        return self._memo[1]

    def problemes(self):
        """Ce qu'il faut dire du dossier du journal, en phrases : points
        relus dans leur copie de secours, fichiers illisibles."""
        self._lus()
        out = []
        for p in getattr(self, "restaures", []):
            out.append(f"Le point {os.path.basename(p)} était abîmé : sa copie "
                       "de secours (.bak) a été relue. Vérifiez-le, puis "
                       "enregistrez-le pour réparer le fichier.")
        for p in getattr(self, "illisibles", []):
            out.append(f"Le fichier {os.path.basename(p)} du journal est "
                       "illisible et n'a pas de copie de secours : ce point "
                       "n'apparaît pas dans la liste.")
        return out

    def _entetes(self):
        """[(numero, horodatage, lieu, voyage)] du plus ancien au plus récent.

        L'en-tête d'un point se lit sans reconstruire son chargement — et
        reconstruire quelques milliers de colis pour retrouver un nom de port
        est exactement ce qui coûtait cher."""
        out = [(int(d.get("numero", 1)), d.get("horodatage", ""),
                d.get("lieu", ""), str(d.get("voyage", "") or ""))
               for _path, d in self._lus()]
        out.sort(key=lambda e: (e[0], e[1]))
        return out

    def points(self):
        """Tous les points, du plus ancien au plus récent (par numéro).

        Les fichiers ne sont relus que si le dossier a changé ; les objets
        `Point`, eux, sont reconstruits à chaque appel. C'est volontaire :
        l'appelant adopte souvent le point rendu et le modifie ensuite (c'est
        le point courant), et il ne doit jamais modifier ce faisant ce que le
        journal croit lire sur le disque."""
        out = []
        for path, d in self._lus():
            p = Point.from_dict(d)
            p.path = path
            out.append(p)
        out.sort(key=lambda p: (p.numero, p.horodatage))
        return out

    def dernier(self) -> Point | None:
        pts = self.points()
        return pts[-1] if pts else None

    def prochain_numero(self) -> int:
        """Le numéro suivant. Un fichier illisible compte aussi : son numéro
        se lit dans son nom (NNNN.json), et on ne veut surtout pas le réutiliser."""
        numeros = [n for n, _h, _l, _v in self._entetes()]
        for path in self.chemins():
            racine = os.path.splitext(os.path.basename(path))[0]
            if racine.isdigit():
                numeros.append(int(racine))
        return (max(numeros) + 1) if numeros else 1

    # ------------------------------------------------------------- écriture
    def chemin_de(self, point: Point) -> str:
        return os.path.join(self.dir, f"{point.numero:04d}.json")

    def enregistrer(self, point: Point) -> str:
        """Écrit le point, et le date de MAINTENANT.

        La date de modification est posée ici et nulle part ailleurs : c'est la
        seule porte par laquelle un point passe sur le disque (`figer` passe
        par elle aussi). Elle n'est jamais saisie — la date que le bord saisit
        est celle du point, l'événement."""
        path = point.path or self.chemin_de(point)
        abime = False
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    json.load(f)
            except (OSError, ValueError):
                abime = True
            try:
                existant = Point.load(path)
            except (OSError, ValueError) as e:
                # illisible ≠ « pas figé » : on n'écrase pas ce qu'on ne sait
                # pas lire — c'est peut-être une archive
                raise PointFige(f"Le fichier du point {point.numero} existe mais est "
                                f"illisible ({e}) : on ne l'écrase pas.") from e
            if existant.fige:
                raise PointFige(f"Le point {point.numero} est figé : il ne se réécrit pas.")
        os.makedirs(self.dir, exist_ok=True)
        avant = point.modifie_le
        point.modifie_le = maintenant()
        try:
            # un fichier abîmé ne devient pas la copie de secours : ce serait
            # écraser la bonne (celle qu'on vient justement de relire)
            with ecriture_atomique(path, bak=not abime) as f:
                json.dump(point.to_dict(), f, ensure_ascii=False, indent=1)
        except Exception:
            # rien n'est allé sur le disque : le point ne doit pas garder en
            # mémoire une date d'enregistrement qui n'a pas eu lieu
            point.modifie_le = avant
            raise
        # ce qui est mémorisé ne vaut plus : on vient de changer le dossier
        self.oublier()
        point.path = path
        return path

    def figer(self, point: Point, resultats: dict | None) -> str:
        """Fige le point : dernier enregistrement, avec l'instantané des
        résultats. Après cela, plus aucune écriture."""
        if point.fige:
            raise PointFige(f"Le point {point.numero} est déjà figé.")
        avant = (point.fige, point.resultats)
        point.fige = True
        point.resultats = resultats
        try:
            path = self.enregistrer(point)
            self.oublier()
            return path
        except Exception:
            # l'écriture a échoué : le point ne doit pas rester figé en mémoire,
            # sinon il ne pourrait plus jamais être enregistré
            point.fige, point.resultats = avant
            raise

    def nouveau(self, depuis: Point | None = None) -> Point:
        """Un point en cours : copie intégrale de `depuis` (par défaut le
        dernier point du journal), ou un point vide s'il n'y a rien."""
        src = depuis if depuis is not None else self.dernier()
        if src is None:
            return Point(numero=self.prochain_numero())
        p = src.copie()
        p.numero = max(p.numero, self.prochain_numero())
        return p

    def lieux_connus(self):
        """Les lieux déjà employés dans ce journal, du plus récent au plus
        ancien : à bord on repasse par les mêmes ports.

        Sur les en-têtes seuls : un nom de port ne demande pas qu'on
        reconstruise le chargement de chaque point."""
        vus = []
        for _n, _h, lieu, _v in reversed(self._entetes()):
            if lieu and lieu not in vus:
                vus.append(lieu)
        return vus

    def voyages_connus(self):
        """Les numéros de voyage déjà employés, du plus récent au plus ancien.

        Même raison que pour les lieux : un voyage couvre plusieurs points, on
        le propose plutôt que de le faire retaper — un « 25-014 » retapé
        « 25-14 » coupe le voyage en deux dans les recherches.

        Sur les en-têtes seuls, comme `lieux_connus`."""
        vus = []
        for _n, _h, _l, voyage in reversed(self._entetes()):
            if voyage and voyage not in vus:
                vus.append(voyage)
        return vus

    def supprimer(self, point: Point):
        """Met le point à la CORBEILLE du journal (`journal/.supprimes/`),
        au lieu de l'effacer : un clic malheureux, ou un poste en lecture
        seule d'avant la 2.21, effaçait un fichier pour de bon (D-77). La
        corbeille n'est lue par personne ; on y récupère un point à la main,
        en le remettant dans `journal/`."""
        path = point.path or self.chemin_de(point)
        if os.path.exists(path):
            corbeille = os.path.join(self.dir, ".supprimes")
            os.makedirs(corbeille, exist_ok=True)
            base = os.path.splitext(os.path.basename(path))[0]
            cible = os.path.join(corbeille, f"{base}-{time.strftime('%Y%m%d-%H%M%S')}.json")
            os.replace(path, cible)
            self.oublier()

    def importer_cas(self, condition: LoadingCondition, libelle: str = "") -> Point:
        """Un ancien cas de chargement devient un point en cours."""
        p = Point(numero=self.prochain_numero(), lieu="",
                  libelle=libelle or condition.nom, condition=copy.deepcopy(condition))
        p.condition.path = ""
        return p
