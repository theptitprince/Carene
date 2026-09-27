# -*- coding: utf-8 -*-
"""Condition de chargement : l'objet manipulé au quotidien.

Chaque chargement est unique, mais on veut pouvoir enregistrer un cas type ou
retrouver un cas passé, le modifier et l'enregistrer sous un autre nom. Une
condition est donc un fichier autonome, rangé dans `conditions/` du dossier du
navire.

Elle contient **tout ce qui est embarqué** :

- le navire lège (inclus ou non) ;
- les **charges posées dans les cales** (`Placement`) — elles appartiennent à
  la condition, pas à la géométrie du navire : deux chargements successifs de
  la même cale n'ont aucune raison d'être identiques ;
- le **manifeste** : ce qu'il y a à embarquer, que le solveur sait répartir ;
- les **soutes** et leur taux de remplissage ;
- les **poids divers** saisis à la main (équipage, vivres, colis hors palette).

Le **matériel du bord** (chariot élévateur, transpalette) est posé comme le
reste, dans `placements`, mais son `Placement` porte un `equipement_id` : la
POSITION appartient au point — elle change à chaque escale et s'archive avec
lui — tandis que l'ENGIN appartient au navire (`equipements_bord.json`). Il
pèse dans le calcul comme n'importe quelle charge, et ne paraît jamais au
manifeste.

Ce module ne dépend pas de Qt et ne calcule rien : il convertit simplement la
condition en `carene.core.condition.Condition`, que le moteur sait traiter.
"""
from __future__ import annotations
from .ecriture import ecriture_atomique

import copy
import datetime as _dt
import json
import os
from dataclasses import dataclass, field

from .core.cargo_model import EquipementBord, ManifestLine, Placement
from .project import CONDITIONS_DIR, PalletLayout


def maintenant() -> str:
    """Horodatage local, à la minute — c'est la précision d'un journal de bord.

    Ici et non dans `journal.py` parce que le brouillon de chargement se date
    lui aussi, et qu'une seule écriture de la date vaut mieux que deux :
    `journal.maintenant` est celle-ci."""
    return _dt.datetime.now().replace(second=0, microsecond=0).isoformat(timespec="minutes")


def lisible(iso: str) -> str:
    """Une date ISO telle qu'on la lit à bord — « — » quand il n'y en a pas.

    On n'affiche jamais une date qu'on n'a pas : un point enregistré avant que
    la date de modification existe n'en porte pas, et il ne faut surtout pas
    lui prêter celle du jour."""
    try:
        return _dt.datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return iso or "—"


def compter_colis(placements) -> int:
    """Les colis posés : chaque niveau d'une pile compte pour un colis.

    Tout ce qui est posé, matériel du bord compris : c'est le plan tel qu'il
    sera rechargé, et non un inventaire de marchandise."""
    return sum(max(1, p.niveaux)
               for lst in (placements or {}).values() for p in (lst or []))


def poids_pose_t(placements) -> float:
    """Le poids de tout ce qui est posé dans les cales, en tonnes."""
    return sum(p.poids_total_t
               for lst in (placements or {}).values() for p in (lst or []))


SONDE = "sonde"
VOLUME = "volume"
POURCENT = "pourcent"      # ancienne saisie : relue, plus jamais proposée


@dataclass
class TankFill:
    """Le relevé d'une capacité : ce qu'on a réellement mesuré.

    À bord on lit une **sonde** (m) ou on connaît un **volume** (m³) ; le
    pourcentage n'est la mesure de personne. La conversion passe par la table
    de jaugeage du navire, seule source légitime.

    La **densité**, elle, est la quatrième grandeur du relevé : le dossier dit
    le produit prévu, le point dit le produit embarqué. Elle se relève comme
    les trois autres, et pour la même raison — on ne modifie pas le dossier du
    navire parce qu'une livraison de gazole pèse 0,84 plutôt que 0,87.
    """

    capacite: str
    mesure: str = SONDE
    valeur: float = 0.0
    # Densité relevée AU POINT DE CHARGEMENT (t/m³), ou None pour celle du
    # dossier. None, et non la valeur du dossier recopiée : un point qui ne
    # porte pas de densité doit continuer de suivre le dossier si celui-ci est
    # corrigé plus tard, et le fichier doit pouvoir dire « rien de relevé ».
    densite: float = None
    # Pourquoi le relevé n'a pas pu être converti (capacité inconnue, table
    # de jaugeage absente ou sans colonne de sonde…) : "" quand tout va bien.
    # Renseigné par `ligne` ; l'interface l'affiche, le fichier ne le garde
    # pas. Sans cela, un relevé illisible valait 0 % en silence.
    probleme: str = field(default="", compare=False, repr=False)

    # ------------------------------------------------------------- densité
    def capacite_chargee(self, navire):
        """La capacité du dossier, relue à la densité de CE point — ou None.

        **Porte unique** de tout ce qui pèse cette capacité : poids, moment de
        carène liquide tabulé et FSM maximal en sortent tous à la même échelle
        (voir `core.navire.Capacity.avec_densite`). Sans densité relevée, elle
        rend la capacité du dossier telle quelle : rien ne change."""
        caps = getattr(navire, "capacities", None) or {}
        cap = caps.get(self.capacite)
        return None if cap is None else cap.avec_densite(self.densite)

    def densite_dossier(self, navire):
        """La densité écrite au dossier, ou None si la capacité est inconnue."""
        caps = getattr(navire, "capacities", None) or {}
        cap = caps.get(self.capacite)
        return None if cap is None else float(cap.density)

    def densite_employee(self, navire):
        """La densité qui fait le poids : celle du point si elle est relevée,
        celle du dossier sinon. None si la capacité est inconnue du navire."""
        if self.densite is not None:
            return float(self.densite)
        return self.densite_dossier(navire)

    def densite_modifiee(self, navire):
        """Le point s'écarte-t-il du dossier sur la densité ?

        La comparaison tolère un demi-millième : c'est la précision à laquelle
        la densité s'affiche et se tape, et un écart plus petit (0,05 %) ne
        veut rien dire sur un produit réel. Retaper la valeur affichée ne doit
        pas faire croire à une modification."""
        d0 = self.densite_dossier(navire)
        if self.densite is None or d0 is None:
            return False
        return abs(float(self.densite) - d0) > 5e-4

    def ligne(self, navire):
        """Ligne de jaugeage correspondant au relevé, ou None (voir alors
        `probleme`). Poids et FSM y sont déjà à la densité du point."""
        self.probleme = ""
        if navire is None or not self.capacite:
            return None
        cap = self.capacite_chargee(navire)
        if cap is None:
            self.probleme = f"capacité « {self.capacite} » inconnue du navire"
            return None
        if not cap.jauge_rows:
            self.probleme = f"pas de table de jaugeage pour « {self.capacite} »"
            return None
        try:
            if self.mesure == VOLUME:
                return cap.at_volume(self.valeur)
            if self.mesure == POURCENT:
                return cap.at_fill_pc(self.valeur)
            return cap.at_sounding(self.valeur)
        except (KeyError, ValueError, IndexError) as e:
            self.probleme = (f"relevé « {self.capacite} » ({self.mesure} = "
                             f"{self.valeur:g}) inexploitable : {e}")
            return None

    def fill_pc(self, navire):
        ligne = self.ligne(navire)
        return float(ligne["Remplissage_pc"]) if ligne else 0.0

    def to_dict(self):
        d = {"capacite": self.capacite, "mesure": self.mesure,
             "valeur": self.valeur}
        # écrite SEULEMENT si elle est relevée : un point sans densité propre
        # se relit à l'identique par les versions qui ignorent cette clé, et
        # le fichier ne prétend pas relever ce que personne n'a relevé
        if self.densite is not None:
            d["densite"] = float(self.densite)
        return d

    @classmethod
    def from_dict(cls, d):
        # absente des points enregistrés avant la densité de point : None,
        # c'est-à-dire « celle du dossier » — exactement ce qu'ils valaient
        densite = d.get("densite")
        densite = float(densite) if densite is not None else None
        if "mesure" not in d and "fill_pc" in d:
            # condition enregistrée par une version antérieure
            return cls(capacite=d.get("capacite", ""), mesure=POURCENT,
                       valeur=float(d.get("fill_pc", 0.0)), densite=densite)
        return cls(capacite=d.get("capacite", ""),
                   mesure=d.get("mesure", SONDE),
                   valeur=float(d.get("valeur", 0.0)), densite=densite)


@dataclass
class ExtraWeight:
    """Un poids saisi directement, avec son centre de gravité."""

    nom: str = "Poids"
    poids_t: float = 0.0
    lcg_m: float = 0.0
    tcg_m: float = 0.0
    vcg_m: float = 0.0

    def to_dict(self):
        return {"nom": self.nom, "poids_t": self.poids_t, "lcg_m": self.lcg_m,
                "tcg_m": self.tcg_m, "vcg_m": self.vcg_m}

    @classmethod
    def from_dict(cls, d):
        return cls(nom=d.get("nom", "Poids"),
                   poids_t=float(d.get("poids_t", 0.0)),
                   lcg_m=float(d.get("lcg_m", 0.0)),
                   tcg_m=float(d.get("tcg_m", 0.0)),
                   vcg_m=float(d.get("vcg_m", 0.0)))


@dataclass
class Brouillon:
    """Un plan de chargement de la CARGAISON mis de côté.

    Avant une escale, on essaie plusieurs plans : tout à l'avant pour l'assiette,
    la charge lourde à fond de cale, la reprise du plan de l'escale précédente.
    On veut pouvoir les garder côte à côte, les comparer, en reprendre un — et
    n'en **valider** qu'un à la fin.

    Un brouillon ne contient que ce qui se DÉCIDE : le **manifeste**, les
    **placements** par cale et les **épontilles en place**. Pas les liquides :
    les sondes sont un relevé, pas un choix — il n'y a qu'une réalité à bord,
    et elle appartient au point, pas au brouillon. Charger un brouillon ne
    touche donc jamais aux caisses.

    `valide` marque celui qui a été retenu : les autres restent (on peut encore
    y revenir) jusqu'à ce qu'on demande de ne garder que le validé.
    """

    nom: str = "Brouillon"
    cree_le: str = field(default_factory=maintenant)
    modifie_le: str = field(default_factory=maintenant)
    manifeste: list = field(default_factory=list)   # [ManifestLine]
    placements: dict = field(default_factory=dict)  # code cale -> [Placement]
    epontilles_en_place: list = field(default_factory=list)
    note: str = ""
    valide: bool = False

    # ------------------------------------------------------------- lecture
    @property
    def nb_colis(self) -> int:
        return compter_colis(self.placements)

    @property
    def poids_t(self) -> float:
        return poids_pose_t(self.placements)

    @property
    def cales_servies(self) -> list:
        """Les cales où ce plan pose quelque chose, dans l'ordre des codes."""
        return [code for code, lst in sorted(self.placements.items()) if lst]

    def meme_plan_que(self, autre: "Brouillon") -> bool:
        """Les deux plans disent-ils la même chose ?

        Le nom, les dates et la note ne comptent pas : deux brouillons peuvent
        porter le même plan sous deux noms. Les cales vides non plus — une cale
        présente avec une liste vide, c'est une cale vide."""
        def vives(pl):
            return {k: v for k, v in (pl or {}).items() if v}
        return (self.manifeste == autre.manifeste
                and vives(self.placements) == vives(autre.placements)
                and sorted(set(self.epontilles_en_place))
                == sorted(set(autre.epontilles_en_place)))

    # ------------------------------------------------------------ fichiers
    def to_dict(self):
        d = {"nom": self.nom, "cree_le": self.cree_le, "modifie_le": self.modifie_le,
             "manifeste": [m.to_dict() for m in self.manifeste],
             "placements": {k: [p.to_dict() for p in v]
                            for k, v in self.placements.items() if v},
             "epontilles_en_place": sorted(set(self.epontilles_en_place))}
        # écrites seulement si elles disent quelque chose : un brouillon sans
        # note ni validation reste un fichier court, lisible à l'œil
        if self.note:
            d["note"] = self.note
        if self.valide:
            d["valide"] = True
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(
            nom=str(d.get("nom") or "Brouillon"),
            cree_le=str(d.get("cree_le") or ""),
            modifie_le=str(d.get("modifie_le") or ""),
            manifeste=[ManifestLine.from_dict(m) for m in d.get("manifeste") or []],
            placements={k: [Placement.from_dict(p) for p in v]
                        for k, v in (d.get("placements") or {}).items()},
            epontilles_en_place=sorted(set(d.get("epontilles_en_place") or [])),
            note=str(d.get("note") or ""),
            valide=bool(d.get("valide", False)))


@dataclass
class LoadingCondition:
    """Un chargement complet, enregistrable et rechargeable."""

    nom: str = "Chargement en cours"
    note: str = ""
    inclure_lege: bool = True
    # CONFIGURATION DE VOILURE portée à ce point — un identifiant de
    # `navire.json` › `profils_vent` (« CARGO », « FS »…). Elle appartient au
    # POINT et non au navire : c'est une décision d'exploitation, elle change
    # d'une manœuvre à l'autre, et elle décide quel critère de vent s'applique
    # (météo IS2008 voiles enroulées, NR500 voilier sous voile). Le défaut est
    # l'identifiant de la configuration sans voile du navire de référence ; sur un
    # navire qui ne le connaît pas, `ProfilsVent.resoudre` retombe sur la
    # première configuration déclarée plutôt que d'échouer.
    voilure: str = "CARGO"
    # ce qui est posé dans les cales : code capacité -> [Placement]
    placements: dict = field(default_factory=dict)
    # ce qu'il reste à embarquer / ce qu'on prévoit d'embarquer
    manifeste: list = field(default_factory=list)  # [ManifestLine]
    tanks: list = field(default_factory=list)      # [TankFill]
    extras: list = field(default_factory=list)     # [ExtraWeight]
    # ÉPONTILLES AMOVIBLES MISES EN PLACE — identifiants (voir
    # `project.Capacity.epontilles`). Leur emplacement appartient au navire ;
    # savoir lesquelles sont posées appartient au POINT : cela change à chaque
    # escale et doit rester archivé avec lui, comme le reste.
    #
    # Par défaut, AUCUNE n'est en place : une épontille que l'officier n'a pas
    # posée ne doit jamais interdire une pose en silence.
    epontilles_en_place: list = field(default_factory=list)
    # LES BROUILLONS DU PLAN DE CHARGEMENT — plusieurs plans de cargaison mis
    # de côté pour ce point, dont un seul finit validé (voir `Brouillon`). Ils
    # appartiennent au point comme le reste : on prépare l'escale, on essaie,
    # on tranche, et l'archive garde ce qu'on a essayé.
    brouillons: list = field(default_factory=list)  # [Brouillon]
    # LE RELEVÉ DE TIRANTS D'EAU du point, tel que le bord l'a lu à la coque
    # (`core.tirants_releves.Releve.to_dict()`), ou None. Il appartient au
    # POINT : c'est une mesure faite ce jour-là, à cette escale, et elle doit
    # rester avec lui — le rapport la cite, et la fenêtre la rouvre telle
    # qu'elle a été saisie. Le poids fictif qu'on en tire, lui, est un poids
    # divers ordinaire : il se voit, se modifie et s'efface comme les autres.
    tirants_releves: dict = None
    path: str = ""                                 # fichier d'où elle vient
    # Matériel du bord repris d'un ancien fichier (lignes « hors manifeste »
    # d'avant l'inventaire) : à verser dans l'inventaire du navire au premier
    # affichage, puis vidé. Ne s'enregistre pas — c'est un état de passage.
    materiel_migre: list = field(default_factory=list, compare=False, repr=False)
    # Ce qu'il y a à dire à l'officier après lecture du fichier (migration…),
    # une fois, dans la barre d'état. Ne s'enregistre pas non plus.
    messages: list = field(default_factory=list, compare=False, repr=False)

    # ------------------------------------------------------------ cales
    def liste(self, code):
        """Charges posées dans cette cale (liste modifiable en place)."""
        return self.placements.setdefault(code, [])

    def hold_lines(self, project, filtre=None):
        """[(code, nom, poids, lcg, tcg, vcg, nb)] par cale chargée.

        `filtre` : prédicat sur le placement, pour ne retenir qu'une partie de
        ce qui est posé (la marchandise, le matériel du bord). Sans filtre —
        et c'est le cas de `to_core` — TOUT ce qui est posé est pesé : le
        moteur additionne le même total qu'avant l'existence du matériel du
        bord, à la tonne près comme au gramme près.

        Une cale RENOMMÉE depuis l'enregistrement du point est retrouvée
        par ses anciens codes (`Capacity.anciens_codes`) : ses colis restent
        dans cette cale, à sa hauteur.

        Une cale que le projet ne connaît plus du tout est conservée en fin
        de liste, nommée « cale inconnue : <code> » : un poids ne disparaît
        pas du bilan en silence. Elle est comptée au plancher le PLUS HAUT du
        navire — et non plus à la quille, qui faisait un KG trop bas donc un
        GM trop beau (1,0 m sur 200 t) : ne sachant pas où est ce poids, on
        le met là où il fait le moins de bien. `cales_inconnues` les signale.

        Deux capacités au même code ne comptent la cargaison qu'une fois
        (l'éditeur de plans refuse désormais le doublon ; un fichier d'avant
        peut encore en porter)."""
        out = []
        connues = []
        vus = set()
        par_ancien = {}
        z_prudent = None
        for _, cap in project.all_capacities():
            z_prudent = cap.z_min if z_prudent is None else max(z_prudent, cap.z_min)
            if cap.code in vus:
                continue
            vus.add(cap.code)
            connues.append((cap.code, cap.name, cap.z_min))
            for ancien in getattr(cap, "anciens_codes", None) or []:
                par_ancien.setdefault(ancien, cap)
        for code in self.placements:
            if code in vus or not self.placements.get(code):
                continue
            cap = par_ancien.get(code)
            if cap is not None:
                connues.append((code, f"{cap.name} (ancien code {code})", cap.z_min))
            else:
                connues.append((code, f"cale inconnue : {code}",
                                z_prudent if z_prudent is not None else 0.0))
        for code, nom, z_min in connues:
            lst = self.placements.get(code) or []
            if not lst:
                continue
            w = lm = tm = vm = 0.0
            n = 0
            for p in lst:
                if filtre is not None and not filtre(p):
                    continue
                pw = p.poids_total_t
                cx, cy = p.centre
                w += pw
                lm += pw * cx
                tm += pw * cy
                vm += pw * p.vcg(z_min)
                n += max(1, p.niveaux)
            if w > 0:
                out.append((code, nom, w, lm / w, tm / w, vm / w, n))
        return out

    def lignes_cargaison(self, project):
        """Les cales, marchandise seule — le matériel du bord à part."""
        return self.hold_lines(project, lambda p: not p.est_materiel_bord)

    def lignes_materiel(self, project):
        """Les cales, matériel du bord seul : ce que l'officier doit pouvoir
        distinguer d'un coup d'œil du fret."""
        return self.hold_lines(project, lambda p: p.est_materiel_bord)

    def placements_materiel(self):
        """[(code cale, placement)] du matériel du bord posé sur le plan."""
        return [(code, p) for code, lst in self.placements.items()
                for p in (lst or []) if p.est_materiel_bord]

    def poses_du_materiel(self, equipement_id):
        """Où cet engin est posé : [(code cale, placement)], vide s'il ne
        l'est pas. Le retirer du plan ne le retire pas de l'inventaire."""
        return [(code, p) for code, p in self.placements_materiel()
                if p.equipement_id == equipement_id]

    def poids_materiel_bord_t(self):
        return sum(p.poids_total_t for _c, p in self.placements_materiel())

    def cales_inconnues(self, project):
        """Codes de cales chargées que le projet ne définit plus — ni comme
        code, ni comme ancien code d'une cale renommée."""
        codes = set()
        for _, cap in project.all_capacities():
            codes.add(cap.code)
            codes.update(getattr(cap, "anciens_codes", None) or [])
        return [c for c, lst in self.placements.items()
                if lst and c not in codes]

    def migrer_codes_cales(self, project):
        """Range sous le code ACTUEL les colis rangés sous un ancien code
        d'une cale renommée (point courant et ses brouillons). Rend le nombre
        de cales déplacées. Ne se fait que sur un point qu'on peut écrire :
        un point figé garde ses clés, et `hold_lines` le lit par les anciens
        codes."""
        alias = {}
        for _, cap in project.all_capacities():
            for ancien in getattr(cap, "anciens_codes", None) or []:
                alias.setdefault(ancien, cap.code)
        n = 0

        def _migrer(placements):
            nonlocal n
            for ancien in [c for c in list(placements) if c in alias]:
                lst = placements.pop(ancien)
                if lst:
                    placements.setdefault(alias[ancien], []).extend(lst)
                    n += 1
        _migrer(self.placements)
        for b in getattr(self, "brouillons", None) or []:
            _migrer(b.placements)
        return n

    def adopter_palettes_legacy(self, project):
        """Convertit d'anciens plans de palettes en grille en placements.

        Les versions antérieures rangeaient un `PalletLayout` sur la capacité :
        une grille de cellules toutes identiques. On en fait des charges
        ordinaires, ce qui permet ensuite de les déplacer une à une."""
        n = 0
        for _, cap in project.all_capacities():
            lay = getattr(cap, "pallet", None)
            if not lay or not lay.cells:
                continue
            ox, oy = cap.pallet_grid_origin()
            lst = self.liste(cap.code)
            for key, count in lay.cells.items():
                i, j = (int(v) for v in key.split(","))
                lst.append(Placement(
                    nom="Palette", longueur_m=lay.pallet_l,
                    largeur_m=lay.pallet_w, hauteur_m=lay.pallet_h,
                    poids_t=lay.pallet_weight,
                    x=ox + i * lay.pallet_l, y=oy + j * lay.pallet_w,
                    niveaux=max(1, int(count)), categorie="Palette",
                    gerbable_max=max(1, int(count))))
                n += 1
            cap.pallet = None
        return n

    # ------------------------------------------------------------ totaux
    # ------------------------------------------------------------ manifeste
    def poids_manifeste_t(self):
        return sum(m.poids_total_t for m in self.manifeste
                   if not getattr(m, "hors_manifeste", False))

    def lignes_a_embarquer(self):
        """Les lignes qui sont de la marchandise — les charges du bord n'en
        sont pas : elles occupent la place, mais rien n'est à embarquer."""
        return [m for m in self.manifeste if not getattr(m, "hors_manifeste", False)]

    def poses_par_type(self, par_lot=False):
        """Exemplaires posés dans les cales ; l'empilement compte.

        Par défaut la clé est le **lot** (la ligne de manifeste d'où vient le
        colis) et, à défaut, le type ou le nom — c'est le cas des chargements
        enregistrés avant que les lots existent.

        Le **matériel du bord** est écarté : il n'a pas de ligne au manifeste,
        et le rattacher par son type (un chariot du bord contre une ligne de
        chariots à embarquer) ferait un compte faux — donc un « reste » faux,
        donc une pose refusée à tort (D-19)."""
        poses = {}
        for lst in self.placements.values():
            for p in lst:
                if p.est_materiel_bord:
                    continue
                cle = (getattr(p, "lot_id", "") or (p.type_code or p.nom)) if par_lot \
                    else (p.type_code or p.nom)
                poses[cle] = poses.get(cle, 0) + max(1, p.niveaux)
        return poses

    def places_par_ligne(self):
        """Ce qui est posé, attribué ligne par ligne du manifeste.

        Chaque colis porte le lot dont il vient : deux lignes du même type
        (« palettes de rhum » et « palettes de café », toutes deux EUR) se
        comptent donc séparément. Les colis d'avant les lots, eux, sont servis
        à l'ancienne : aux lignes du même type, dans l'ordre, le surplus à la
        dernière — un excédent doit se voir quelque part."""
        par_lot = self.poses_par_type(par_lot=True)
        attribue = [0] * len(self.manifeste)
        reste_par_cle = {}
        # DEUX index séparés, et ce n'est pas un détail : un identifiant de lot
        # et un code de type ne vivent pas dans le même espace de noms, et un
        # seul dictionnaire pour les deux ferait tomber le surplus d'un lot sur
        # la ligne d'un type qui porterait le même texte.
        derniere_par_lot = {}
        derniere_par_type = {}
        for i, m in enumerate(self.manifeste):
            pris = par_lot.pop(m.lot_id, 0)
            attribue[i] = min(max(0, m.quantite), pris)
            if pris > attribue[i]:
                reste_par_cle[m.lot_id] = pris - attribue[i]
                derniere_par_lot[m.lot_id] = i
            derniere_par_type[m.type_code or m.nom] = i
        # ce qui n'a pas de lot connu : rattaché par type, comme avant
        for cle, n in par_lot.items():
            for i, m in enumerate(self.manifeste):
                if (m.type_code or m.nom) != cle or n <= 0:
                    continue
                place = min(max(0, m.quantite) - attribue[i], n)
                if place > 0:
                    attribue[i] += place
                    n -= place
            if n > 0 and cle in derniere_par_type:
                attribue[derniere_par_type[cle]] += n
        for cle, n in reste_par_cle.items():
            attribue[derniere_par_lot[cle]] += n
        return attribue

    def to_core(self, navire, project):
        """Construit la condition du moteur (lège + cales + poids + soutes)."""
        from .core import condition as core_condition
        cond = core_condition.Condition(navire=navire,
                                        inclure_lege=self.inclure_lege,
                                        profil_vent=self.voilure or None)
        for code, nom, w, lcg, tcg, vcg, _n in self.hold_lines(project):
            cond.cargo.append(core_condition.CargoItem(
                nom=f"Cale {code}", poids_t=w,
                lcg_m=lcg, tcg_m=tcg, vcg_m=vcg, code_cale=code))
        for e in self.extras:
            if e.poids_t:
                cond.cargo.append(core_condition.CargoItem(
                    nom=e.nom, poids_t=e.poids_t, lcg_m=e.lcg_m,
                    tcg_m=e.tcg_m, vcg_m=e.vcg_m))
        connues = getattr(navire, "capacities", {}) or {}
        for t in self.tanks:
            # une capacité que le navire ne connaît plus (dossier modifié
            # depuis l'enregistrement du cas) ne peut pas être pesée : on ne
            # l'invente pas, le panneau la signale comme orpheline
            if t.capacite and t.capacite in connues:
                # la densité relevée suit la capacité jusqu'au moteur : sans
                # elle, le calcul aurait pesé le contenu du dossier et non
                # celui qui est à bord
                cond.tanks.append(core_condition.TankState(
                    capacite=t.capacite, fill_pc=t.fill_pc(navire),
                    densite=t.densite))
        return cond

    def synchroniser_capacites(self, navire):
        """Aligne le relevé sur les capacités réellement définies au navire.

        Les capacités appartiennent au navire, pas au chargement : la liste
        est donc toujours complète, dans l'ordre du dossier, et l'officier n'a
        qu'à porter la mesure en face. Les capacités absentes du relevé y sont
        ajoutées à zéro ; celles que le navire ne connaît plus sont conservées
        en fin de liste, pour qu'un cas ancien ne perde pas silencieusement un
        poids — le panneau les affiche comme orphelines.
        """
        caps = getattr(navire, "capacities", None) or {}
        if not caps:
            return 0
        vus = {t.capacite: t for t in self.tanks}
        ordre, ajouts = [], 0
        for nom, cap in caps.items():
            t = vus.pop(nom, None)
            if t is None:
                t = TankFill(nom, SONDE if cap.a_sondage else VOLUME, 0.0)
                ajouts += 1
            ordre.append(t)
        ordre.extend(vus.values())            # orphelines, à la fin
        self.tanks = ordre
        return ajouts

    def is_empty(self, project):
        return not (self.inclure_lege or self.hold_lines(project)
                    or self.tanks or [e for e in self.extras if e.poids_t])

    # ------------------------------------------------------- épontilles
    def epontille_en_place(self, eid) -> bool:
        """Cette épontille est-elle posée à ce point ?"""
        return eid in set(self.epontilles_en_place)

    def poser_epontille(self, eid, en_place=True) -> bool:
        """Met l'épontille en place (ou la dépose). Retourne True si l'état a
        changé — l'appelant a alors une charge à recalculer et un message à
        dire : décrire le navire n'est jamais silencieux."""
        actuel = set(self.epontilles_en_place)
        avant = eid in actuel
        if bool(en_place) == avant:
            return False
        if en_place:
            actuel.add(eid)
        else:
            actuel.discard(eid)
        self.epontilles_en_place = sorted(actuel)
        return True

    def epontilles_inconnues(self, project):
        """Les épontilles en place que la géométrie ne connaît plus.

        Un emplacement supprimé dans l'éditeur de plans laisse son
        identifiant dans les points qui le portaient : il ne contraint plus
        rien (la cale ne le retrouve pas), mais il ne faut pas le taire —
        c'est le pendant de `cales_inconnues`."""
        connus = {e.get("id") for _d, _c, e in project.all_epontilles()}
        return [i for i in self.epontilles_en_place if i not in connus]

    def epontilles_de(self, cap):
        """Les identifiants en place qui appartiennent à CETTE cale."""
        ids = set(self.epontilles_en_place)
        return [e.get("id") for e in getattr(cap, "epontilles", []) or []
                if e.get("id") in ids]

    # --------------------------------------------- brouillons du plan
    # Un brouillon est un plan de CARGAISON mis de côté : manifeste,
    # placements, épontilles en place. Les copies sont toujours PROFONDES
    # dans les deux sens — sans cela, déplacer un colis du plan en cours
    # déplacerait aussi celui du brouillon, et le brouillon ne serait plus un
    # brouillon mais un deuxième nom pour la même chose.
    def plan_en_cours(self) -> Brouillon:
        """Le plan de chargement en cours, copié en profondeur.

        Il n'est pas ajouté à la liste : c'est l'instantané dont se servent
        `enregistrer_brouillon` et la comparaison avec les brouillons."""
        return Brouillon(
            manifeste=copy.deepcopy(self.manifeste),
            placements={k: copy.deepcopy(v)
                        for k, v in self.placements.items() if v},
            epontilles_en_place=sorted(set(self.epontilles_en_place)))

    def nom_de_brouillon_propose(self) -> str:
        """Le nom proposé pour le prochain brouillon : « Brouillon N — date ».

        Numéroté et daté, parce que trois brouillons nommés « Brouillon » ne
        se distinguent plus, et qu'on ne se souvient pas le lendemain de
        l'ordre dans lequel on les a faits."""
        return f"Brouillon {len(self.brouillons) + 1} — {lisible(maintenant())}"

    def enregistrer_brouillon(self, nom: str = "", note: str = "") -> Brouillon:
        """Met le plan en cours de côté sous ce nom. Rend le brouillon créé."""
        b = self.plan_en_cours()
        b.nom = (nom or "").strip() or self.nom_de_brouillon_propose()
        b.note = note or ""
        self.brouillons.append(b)
        return b

    def charger_brouillon(self, i: int) -> Brouillon:
        """Le plan en cours devient une COPIE de ce brouillon.

        Les liquides, les poids divers et le lège ne bougent pas : ce sont des
        relevés du point, pas des décisions de chargement."""
        b = self.brouillons[i]
        self.manifeste = copy.deepcopy(b.manifeste)
        self.placements = {k: copy.deepcopy(v) for k, v in b.placements.items() if v}
        self.epontilles_en_place = sorted(set(b.epontilles_en_place))
        return b

    def renommer_brouillon(self, i: int, nom: str) -> bool:
        """Renomme le brouillon. Faux si le nom est vide ou inchangé."""
        b = self.brouillons[i]
        nom = (nom or "").strip()
        if not nom or nom == b.nom:
            return False
        b.nom = nom
        b.modifie_le = maintenant()
        return True

    def supprimer_brouillon(self, i: int) -> Brouillon:
        return self.brouillons.pop(i)

    def valider_brouillon(self, i: int) -> Brouillon:
        """Retient ce brouillon : on le CHARGE et on le marque validé.

        Valider sans charger laisserait le plan en cours dire autre chose que
        le plan retenu — le pire des deux mondes. Un seul brouillon est validé
        à la fois ; les autres restent, et `ne_garder_que_le_valide` les efface
        quand on est sûr."""
        b = self.charger_brouillon(i)
        for autre in self.brouillons:
            autre.valide = (autre is b)
        b.modifie_le = maintenant()
        return b

    def index_du_brouillon_valide(self):
        """L'index du brouillon validé, ou None s'il n'y en a pas."""
        for i, b in enumerate(self.brouillons):
            if b.valide:
                return i
        return None

    def ne_garder_que_le_valide(self) -> int:
        """N'en garde que le validé. Rend le nombre de brouillons effacés (0
        s'il n'y a pas de validé : on n'efface jamais sans savoir quoi garder)."""
        i = self.index_du_brouillon_valide()
        if i is None:
            return 0
        efface = len(self.brouillons) - 1
        self.brouillons = [self.brouillons[i]]
        return efface

    def index_du_brouillon_du_plan(self):
        """L'index du brouillon qui dit EXACTEMENT le plan en cours, ou None.

        C'est ce qui permet de ne pas harceler l'officier : on ne propose
        d'enregistrer le plan en cours avant d'en charger un autre que s'il
        n'est pas déjà rangé quelque part."""
        courant = self.plan_en_cours()
        for i, b in enumerate(self.brouillons):
            if b.meme_plan_que(courant):
                return i
        return None

    # ------------------------------------------------------------ fichiers
    def to_dict(self):
        d = {
            "format": "carene-condition",
            "version": 1,
            "nom": self.nom,
            "note": self.note,
            "inclure_lege": self.inclure_lege,
            "voilure": self.voilure,
            "placements": {k: [p.to_dict() for p in v]
                           for k, v in self.placements.items() if v},
            "manifeste": [m.to_dict() for m in self.manifeste],
            "tanks": [t.to_dict() for t in self.tanks],
            "extras": [e.to_dict() for e in self.extras],
            "epontilles_en_place": sorted(set(self.epontilles_en_place)),
        }
        # ABSENT quand il n'y en a pas, comme les brouillons : un point sans
        # relevé s'écrit exactement comme avant que les relevés existent
        if self.tirants_releves:
            d["tirants_releves"] = dict(self.tirants_releves)
        # ABSENTE quand il n'y en a pas : un point sans brouillon s'écrit
        # exactement comme avant que les brouillons existent, et se relit tel
        # quel par les versions qui ne les connaissent pas
        if self.brouillons:
            d["brouillons"] = [b.to_dict() for b in self.brouillons]
        return d

    @classmethod
    def from_dict(cls, d):
        cond = cls(
            nom=d.get("nom", "Chargement"),
            note=d.get("note", ""),
            inclure_lege=bool(d.get("inclure_lege", True)),
            # un point enregistré avant que la voilure existe décrit un navire
            # voiles enroulées : c'est la configuration par défaut, et le
            # relire ne change donc aucun de ses chiffres
            voilure=str(d.get("voilure") or "CARGO"),
            placements={k: [Placement.from_dict(p) for p in v]
                        for k, v in (d.get("placements") or {}).items()},
            manifeste=[ManifestLine.from_dict(m) for m in d.get("manifeste", [])],
            tanks=[TankFill.from_dict(t) for t in d.get("tanks", [])],
            extras=[ExtraWeight.from_dict(e) for e in d.get("extras", [])],
            # un point d'avant les épontilles se relit tel quel : aucune n'est
            # en place, ce qui est bien l'état du navire qu'il décrit
            epontilles_en_place=sorted(set(d.get("epontilles_en_place") or [])),
            # de même pour les brouillons : un point d'avant n'en a pas, et
            # n'en a jamais eu — la liste vide dit vrai
            brouillons=[Brouillon.from_dict(b) for b in d.get("brouillons") or []],
            # un point d'avant les relevés n'en porte pas : None dit vrai
            tirants_releves=(dict(d["tirants_releves"])
                             if d.get("tirants_releves") else None),
        )
        cond.migrer_charges_du_bord()
        return cond

    # -------------------------------------------------- matériel du bord
    def migrer_charges_du_bord(self):
        """Reprend les anciennes lignes « du bord » du manifeste en matériel.

        Avant l'inventaire, un engin du bord était une ligne de manifeste
        marquée `hors_manifeste` : elle s'affichait au milieu de la
        marchandise, ce que le bord ne voulait pas. On la sort du manifeste et
        on en fait un **matériel du bord** ; les colis déjà posés qui en
        venaient deviennent des placements de cet engin — même position, même
        poids, même centre de gravité. **Aucun total ne change** : on ne
        touche qu'à l'étiquette, jamais à la géométrie.

        Retourne le nombre de lignes reprises. Les engins sont déposés dans
        `materiel_migre` : c'est l'interface qui les verse dans l'inventaire
        du navire (`adopter_materiel`), parce que ce module ne sait pas où le
        navire est rangé."""
        anciennes = [m for m in self.manifeste
                     if getattr(m, "hors_manifeste", False)]
        if not anciennes:
            return 0
        for m in anciennes:
            # l'identifiant dérive du lot : rejouer la migration sur le même
            # fichier redonne le même engin, jamais un doublon
            eid = "MB_" + (m.lot_id or "")
            self.materiel_migre.append(EquipementBord(
                id=eid, nom=m.nom, categorie=m.categorie or "Engin",
                longueur_m=m.longueur_m, largeur_m=m.largeur_m,
                hauteur_m=m.hauteur_m, poids_t=m.poids_t,
                gerbable_max=max(1, int(m.gerbable_max or 1)),
                rotation_permise=m.rotation_permise,
                couleur=m.couleur, note=getattr(m, "note", ""), a_bord=True,
                source="repris d'une ligne « charge du bord » du manifeste"))
            for lst in self.placements.values():
                for p in lst:
                    if p.lot_id == m.lot_id:
                        p.equipement_id = eid
                        p.lot_id = ""
                        p.epingle = True      # le solveur ne le touche plus
        self.manifeste = [m for m in self.manifeste
                          if not getattr(m, "hors_manifeste", False)]
        self.messages.append(
            f"{len(anciennes)} charge(s) du bord sorties du manifeste et "
            "reprises dans le matériel du bord — position, poids et stabilité "
            "inchangés.")
        return len(anciennes)

    def adopter_materiel(self, inventaire):
        """Verse dans l'inventaire du navire le matériel repris d'un ancien
        fichier. Un engin déjà connu n'est pas réécrit : l'inventaire du
        navire fait foi, la migration ne fait que compléter."""
        n = 0
        for e in self.materiel_migre:
            if inventaire is not None and inventaire.get(e.id) is None:
                inventaire.add(e)
                n += 1
        self.materiel_migre = []
        return n

    def dire_les_messages(self):
        """Rend les messages en attente et vide la file : on les dit une fois."""
        msgs, self.messages = list(self.messages), []
        return msgs

    def save(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with ecriture_atomique(path) as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=1)
        self.path = path
        return path

    @classmethod
    def load(cls, path: str) -> "LoadingCondition":
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("format") != "carene-condition":
            raise ValueError("Ce fichier n'est pas une condition de chargement.")
        cond = cls.from_dict(d)
        cond.path = path
        return cond


# ------------------------------------------------------------------ dossier
def conditions_dir(ship_folder: str) -> str:
    return os.path.join(ship_folder, CONDITIONS_DIR)


def list_conditions(ship_folder: str):
    """[(nom, chemin)] des conditions enregistrées avec ce navire."""
    d = conditions_dir(ship_folder)
    if not os.path.isdir(d):
        return []
    out = []
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(d, fn)
        try:
            with open(path, encoding="utf-8") as f:
                nom = json.load(f).get("nom", fn[:-5])
        except (OSError, ValueError):
            nom = fn[:-5]
        out.append((nom, path))
    return out


def renommer_type_code(condition, ancien, nouveau):
    """Un type du catalogue a changé de code (D-69) : tout ce qui, dans ce
    chargement, se référait à l'ancien code se réfère au nouveau — lignes du
    manifeste, colis posés, et les brouillons du point. Rend le nombre
    d'objets retouchés. Les dimensions ne bougent pas : un manifeste porte
    les siennes, le type ne fait que les proposer (D-36)."""
    ancien, nouveau = str(ancien or ""), str(nouveau or "")
    if not ancien or not nouveau or ancien == nouveau or condition is None:
        return 0
    n = 0

    def _lot(manifeste, placements):
        nonlocal n
        for m in manifeste or []:
            if getattr(m, "type_code", "") == ancien:
                m.type_code = nouveau
                n += 1
        for lst in (placements or {}).values():
            for p in lst:
                if getattr(p, "type_code", "") == ancien:
                    p.type_code = nouveau
                    n += 1

    _lot(condition.manifeste, condition.placements)
    for b in getattr(condition, "brouillons", None) or []:
        _lot(b.manifeste, b.placements)
    return n


def safe_filename(nom: str) -> str:
    keep = "-_() "
    cleaned = "".join(c if (c.isalnum() or c in keep) else "_" for c in nom)
    return (cleaned.strip() or "condition") + ".json"
