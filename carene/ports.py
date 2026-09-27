# -*- coding: utf-8 -*-
"""Les escales du navire : un nom, un code, un pays.

Taper « Pointe-à-Pitre » à la main dans chaque ligne de manifeste, c'est trois
orthographes au bout de trois escales — et un pointage de déchargement qui
sépare « Pointe à Pitre » de « Pointe-à-Pitre ». Le bord travaille sur une
liste : on choisit, on ne tape pas.

Le code est celui du **UN/LOCODE** (deux lettres de pays + trois lettres :
FRLEH pour Le Havre). Il est **facultatif** : une escale sans code reste une
escale, et le logiciel n'en invente jamais un. Ce fichier est écrit noir sur
blanc parce que c'est la règle du projet — aucune valeur non vérifiée n'est
présentée comme un résultat.

Deux listes, et elles ne servent pas à la même chose :

- **le monde** — les 17 573 ports du UN/LOCODE, livrés avec le logiciel
  (`donnees/ports_unlocode.csv.gz`). On ne sait pas quel sera le prochain
  contrat : on cherche n'importe quel port de la planète par son nom ou son
  code, sans rien télécharger ni taper ;
- **le navire** — `ports.json` dans son dossier : les escales de SA ligne,
  celles qu'on retrouve en tête de liste, plus les quais que la CEE-ONU ne
  connaît pas. Elle se remplit toute seule à l'usage.

Pas de Qt ici.
"""
from __future__ import annotations
from .ecriture import ecriture_atomique

import csv
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field

FICHIER = "ports.json"
FORMAT = "carene-ports"
# « En mer » n'est pas une escale, mais c'est un lieu de point du journal :
# on le propose avec les ports sans le ranger parmi eux.
EN_MER = "En mer"


def _sans_accent(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn").lower()


def _cle_nom(nom):
    """La clé de comparaison d'un NOM d'escale.

    Sans accents ni casse — comme `_sans_accent` — mais aussi sans les
    séparations qui changent d'une main à l'autre : « Pointe à Pitre »,
    « Pointe-à-Pitre » et « pointe_a_pitre » sont **le même quai**. Sans cela,
    deux orthographes du même port sortent deux feuilles de pointage, et c'est
    précisément ce qu'on cherche à éviter. Le trait d'union ne disparaît pas de
    l'affichage : seule la comparaison l'ignore."""
    return re.sub(r"[\s\-_'’./]+", " ", _sans_accent(nom)).strip()


# Nom public de la clé de comparaison : le solveur de chargement en a besoin
# pour rapprocher le `port_dechargement` d'une ligne de manifeste d'une escale
# de la liste du bord (ordre des escales, `Reglages.respecter_escales`). Il
# n'avait aucune raison de réécrire cette normalisation pour son compte : deux
# façons de comparer deux noms de port, c'est un jour où elles divergent.
cle_nom = _cle_nom


def meme_port(a, b):
    """Deux écritures désignent-elles la même escale ? Sans liste ni code —
    c'est la question qu'on se pose en regroupant des lignes de manifeste."""
    ca, cb = _cle_nom(a), _cle_nom(b)
    return bool(ca) and ca == cb


def code_valide(code):
    """Un UN/LOCODE bien formé : deux lettres de pays, trois de localité.

    On vérifie la FORME, pas l'existence — vérifier l'existence demanderait la
    liste officielle, et c'est justement ce qu'on importe quand on l'a."""
    return bool(re.fullmatch(r"[A-Z]{2}[A-Z2-9]{3}", (code or "").strip().upper()))


@dataclass
class Port:
    """Une escale. `code` vide = code inconnu, à compléter — jamais deviné."""

    nom: str = ""
    code: str = ""                 # UN/LOCODE, ex. FRLEH
    pays: str = ""                 # nom du pays, en clair
    note: str = ""
    # d'où vient l'entrée : "bord" (saisie ou déduite de l'usage) ou
    # "UN/LOCODE" (importée du fichier officiel de la CEE-ONU)
    source: str = "bord"

    @property
    def etiquette(self):
        """Ce qu'on lit dans une liste déroulante : « FRLEH — Le Havre »."""
        return f"{self.code} — {self.nom}" if self.code else self.nom

    def to_dict(self):
        return {"nom": self.nom, "code": self.code, "pays": self.pays,
                "note": self.note, "source": self.source}

    @classmethod
    def from_dict(cls, d):
        return cls(nom=str(d.get("nom", "") or ""),
                   code=str(d.get("code", "") or "").strip().upper(),
                   pays=str(d.get("pays", "") or ""),
                   note=str(d.get("note", "") or ""),
                   source=str(d.get("source", "bord") or "bord"))


class Ports:
    """La liste des escales du navire."""

    def __init__(self, ports=None, messages=None):
        self.ports = list(ports or [])
        self.messages = list(messages or [])

    # ------------------------------------------------------------- lecture
    def __len__(self):
        return len(self.ports)

    def __iter__(self):
        return iter(self.ports)

    def par_nom(self, nom):
        cible = _cle_nom(nom)
        if not cible:
            return None
        return next((p for p in self.ports if _cle_nom(p.nom) == cible), None)

    def par_code(self, code):
        c = (code or "").strip().upper()
        return next((p for p in self.ports if p.code == c), None) if c else None

    def trouver(self, texte):
        """Un port depuis ce que l'officier a tapé ou choisi : « FRLEH »,
        « Le Havre », « FRLEH — Le Havre ». None si on ne reconnaît rien."""
        t = (texte or "").strip()
        if not t:
            return None
        if "—" in t:
            gauche, _sep, droite = t.partition("—")
            return (self.par_code(gauche.strip()) or self.par_nom(droite.strip())
                    or self.par_nom(t))
        return self.par_code(t) or self.par_nom(t)

    def nom_de(self, texte):
        """Le nom d'escale à retenir dans une ligne de manifeste ou un point :
        celui de la liste s'il est reconnu, sinon le texte tel quel — on ne
        perd jamais ce que l'officier a écrit."""
        p = self.trouver(texte)
        return p.nom if p is not None else (texte or "").strip()

    def etiquettes(self):
        return [p.etiquette for p in self.ports]

    def chercher(self, filtre):
        """Les ports dont le nom, le code ou le pays contient `filtre`.

        Comparaison sur la clé de nom : « pointe a pitre » retrouve
        « Pointe-à-Pitre » — l'officier ne doit pas avoir à deviner où le bord
        a mis les traits d'union."""
        f = _cle_nom(filtre)
        if not f:
            return list(self.ports)
        return [p for p in self.ports
                if f in _cle_nom(f"{p.code} {p.nom} {p.pays}")]

    # ------------------------------------------------------------- écriture
    def ajouter(self, port):
        """Ajoute ou complète. Deux escales de même nom n'en font qu'une ; un
        code déjà connu ne se réattribue pas à un autre nom."""
        if not (port.nom or "").strip():
            return None
        existant = self.par_nom(port.nom) or (self.par_code(port.code)
                                              if port.code else None)
        if existant is None:
            self.ports.append(port)
            return port
        if port.code and not existant.code:
            existant.code = port.code
        if port.pays and not existant.pays:
            existant.pays = port.pays
        if port.note and not existant.note:
            existant.note = port.note
        return existant

    def retirer(self, nom):
        p = self.par_nom(nom)
        if p is not None:
            self.ports.remove(p)
        return p

    def apprendre(self, noms):
        """Range dans la liste les escales déjà employées quelque part (points
        du journal, lignes de manifeste). Sans code : il se complète à la main
        ou par l'import officiel. Retourne le nombre d'entrées nouvelles."""
        n = 0
        for nom in noms:
            nom = (nom or "").strip()
            if not nom or nom == EN_MER or self.trouver(nom) is not None:
                continue
            self.ports.append(Port(nom=nom, source="bord"))
            n += 1
        return n

    def trier(self):
        """Par pays puis par nom : c'est ainsi qu'on cherche une escale."""
        self.ports.sort(key=lambda p: (_sans_accent(p.pays), _sans_accent(p.nom)))

    # ------------------------------------------------------------- fichiers
    @classmethod
    def load(cls, dossier):
        chemin = os.path.join(dossier or "", FICHIER)
        if not os.path.exists(chemin):
            return cls()
        try:
            with open(chemin, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError) as e:
            return cls(messages=[f"Liste des escales illisible ({e}) : "
                                 "une liste vide est employée."])
        lignes = d.get("ports", d if isinstance(d, list) else [])
        return cls([Port.from_dict(x) for x in lignes])

    def save(self, dossier):
        chemin = os.path.join(dossier, FICHIER)
        with ecriture_atomique(chemin) as f:
            json.dump({"format": FORMAT, "version": 1,
                       "note": "Escales du navire. Le code est un UN/LOCODE ; "
                               "vide = inconnu, à compléter. Aucun code n'est "
                               "deviné par le logiciel.",
                       "ports": [p.to_dict() for p in self.ports]},
                      f, ensure_ascii=False, indent=1)
        return chemin

    # ------------------------------------------------------- import officiel
    def importer_unlocode(self, chemin, pays=None):
        """Ajoute les escales du fichier CEE-ONU (`UNLOCODE CodeListPart*.csv`).

        Le fichier officiel n'est pas redistribuable avec le logiciel :
        l'armement le télécharge une fois sur unece.org et l'importe ici. Le
        format est celui de la CEE-ONU, sans en-tête : Change, Country,
        Location, Name, NameWoDiacritics, Subdivision, Function, Status, Date,
        IATA, Coordinates, Remarks. `pays` (liste de codes ISO) limite
        l'import — la liste entière fait plus de cent mille lignes, et un
        navire n'a pas besoin de l'Ouzbékistan.

        Ne retient que les localités dont la fonction porte le chiffre **1**
        (port maritime). Retourne (ajoutés, lus)."""
        garder = {c.strip().upper() for c in (pays or [])} or None
        ajoutes = lus = 0
        with open(chemin, encoding="utf-8", errors="replace", newline="") as f:
            for ligne in csv.reader(f):
                if len(ligne) < 8:
                    continue
                _chg, pays_code, loc, nom, sans_acc, _sub, fonction = ligne[:7]
                pays_code = (pays_code or "").strip().upper()
                loc = (loc or "").strip().upper()
                if not pays_code or not loc or len(loc) != 3:
                    continue           # ligne de titre de pays
                lus += 1
                if garder is not None and pays_code not in garder:
                    continue
                if "1" not in (fonction or ""):
                    continue           # pas un port maritime
                nom = (nom or sans_acc or "").strip()
                if not nom:
                    continue
                avant = len(self.ports)
                self.ajouter(Port(nom=nom, code=pays_code + loc,
                                  pays=pays_code, source="UN/LOCODE"))
                ajoutes += len(self.ports) - avant
        self.trier()
        return ajoutes, lus


# ------------------------------------------------------------------ le monde
# La liste officielle CEE-ONU, livrée avec le logiciel : 17 573 ports maritimes
# et fluviaux (fonctions 1 et 8) du UN/LOCODE 2023-1, 240 ko compressés. Elle
# est lue à la PREMIÈRE recherche seulement — ouvrir l'application ne doit pas
# coûter le déballage de cent mille lignes.
_MONDE = None
DOSSIER_DONNEES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "donnees")
SOURCE_MONDE = ("UN/LOCODE 2023-1 (CEE-ONU) — ports maritimes et fluviaux, "
                "fonctions 1 et 8")


def _charger_monde():
    global _MONDE
    if _MONDE is not None:
        return _MONDE
    import gzip
    pays = {}
    chemin_pays = os.path.join(DOSSIER_DONNEES, "pays_unlocode.csv.gz")
    try:
        with gzip.open(chemin_pays, "rt", encoding="utf-8", newline="") as f:
            for ligne in csv.DictReader(f):
                pays[ligne["code"]] = ligne["nom"]
    except (OSError, ValueError):                   # pragma: no cover
        pays = {}
    ports = []
    chemin = os.path.join(DOSSIER_DONNEES, "ports_unlocode.csv.gz")
    try:
        with gzip.open(chemin, "rt", encoding="utf-8", newline="") as f:
            for ligne in csv.DictReader(f):
                ports.append(Port(nom=ligne["nom"], code=ligne["code"],
                                  pays=pays.get(ligne["pays"], ligne["pays"]),
                                  source="UN/LOCODE"))
    except (OSError, ValueError):                   # pragma: no cover
        ports = []
    _MONDE = Ports(ports)
    # index de recherche : une clé sans accents par port, préparée une fois
    _MONDE._index = [(_sans_accent(f"{p.code} {p.nom} {p.pays}"), p)
                     for p in _MONDE.ports]
    return _MONDE


def monde():
    """Tous les ports du UN/LOCODE. Vide si le fichier livré manque."""
    return _charger_monde()


def chercher_partout(filtre, navire=None, limite=60):
    """Les ports qui correspondent, **escales du navire d'abord**.

    C'est la recherche des listes déroulantes : on tape « pointe », « FRLEH »
    ou « guadeloupe » et on choisit. Le nom se compare sans accents ni casse ;
    un code exact passe devant tout le reste."""
    f = _sans_accent(filtre).strip()
    vus, out = set(), []

    def prendre(p):
        cle = (p.code, _sans_accent(p.nom))
        if cle in vus:
            return
        vus.add(cle)
        out.append(p)

    if navire is not None:
        exact = navire.par_code(filtre.strip().upper()) if f else None
        if exact is not None:
            prendre(exact)
        for p in navire.chercher(filtre):
            prendre(p)
    m = _charger_monde()
    if f:
        exact = m.par_code(filtre.strip().upper())
        if exact is not None:
            prendre(exact)
        # le nom qui COMMENCE par ce qu'on tape passe devant celui qui le
        # contient : « bord » doit rendre Bordeaux avant Saint-Amand-Bordeaux
        debuts, dedans = [], []
        for cle, p in m._index:
            if cle.startswith(f) or f" {f}" in cle:
                debuts.append(p)
            elif f in cle:
                dedans.append(p)
            if len(debuts) >= limite * 2:
                break
        for p in debuts + dedans:
            prendre(p)
            if len(out) >= limite:
                break
    elif navire is None:
        out = m.ports[:limite]
    return out[:limite]


def ports_du_navire(dossier, condition=None, journal=None):
    """La liste des escales, complétée par tout ce qui est déjà employé.

    C'est le point d'entrée de l'interface : elle apprend au passage les ports
    tapés avant que cette liste existe, sans jamais leur inventer de code."""
    liste = Ports.load(dossier)
    vus = []
    if condition is not None:
        for m in getattr(condition, "manifeste", []) or []:
            vus += [m.port_chargement, m.port_dechargement]
    if journal is not None:
        try:
            vus += list(journal.lieux_connus())
        except Exception:                       # pragma: no cover
            pass
    liste.apprendre(vus)
    return liste


def dossier_du_navire(win):
    """Le dossier du navire ouvert, vu depuis la fenêtre principale.

    On le lit sur le journal (`win.journal.folder`) plutôt que par
    `app_paths` : c'est la même valeur, sans faire entrer Qt dans ce fichier,
    et une fenêtre postiche de test le porte aussi."""
    for attr, source in (("folder", getattr(win, "journal", None)),
                         ("navire_virtuel_path", getattr(win, "project", None))):
        dossier = getattr(source, attr, "") or ""
        if dossier and os.path.isdir(dossier):
            return dossier
    return ""


def liste_du_bord(win, recharger=False):
    """La liste des escales du navire ouvert, mémorisée sur la fenêtre.

    Tout ce qui demande un port (manifeste, journal, composition d'un lot,
    exports) passe par ici : une seule liste en mémoire, donc une escale
    ajoutée quelque part est connue partout. La fenêtre principale peut la
    poser elle-même dans `win.ports` à l'ouverture du navire ; tant qu'elle ne
    le fait pas, elle est lue ici au premier besoin — les panneaux marchent
    dans les deux cas, et un panneau monté sur une fenêtre postiche aussi."""
    liste = getattr(win, "ports", None)
    dossier = dossier_du_navire(win)
    connu = getattr(win, "_ports_dossier", dossier)
    if isinstance(liste, Ports) and not recharger and connu == dossier:
        return liste
    liste = ports_du_navire(dossier, getattr(win, "condition", None),
                            getattr(win, "journal", None))
    try:
        win.ports = liste
        win._ports_dossier = dossier
    except AttributeError:                      # pragma: no cover
        pass
    return liste


def etiquette_de(liste, nom):
    """« FRLEH — Le Havre » quand la liste du bord connaît l'escale, le nom tel
    quel sinon.

    C'est l'écriture des tableaux, des feuilles de pointage et des exports. On
    ne va PAS chercher le code dans la liste mondiale au passage : deux ports
    du monde portent le même nom (Santa Marta, Victoria, Portsmouth…), et
    afficher un code non choisi par le bord serait présenter comme vérifié ce
    qui ne l'est pas."""
    texte = (nom or "").strip()
    if not texte or liste is None:
        return texte
    p = liste.trouver(texte)
    return p.etiquette if p is not None else texte
