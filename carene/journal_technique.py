# -*- coding: utf-8 -*-
"""Le journal technique : ce que Carène a fait, et ce qui lui est arrivé.

Carène part en essai à bord. Quand quelque chose se passe mal, la personne
qui le constate est en passerelle, pas devant un terminal : elle ne peut ni
relire une console qu'elle a déjà fermée, ni dire de quelle version il
s'agit. Ce module écrit donc, en continu et sans qu'on le demande, un
fichier texte dans le dossier des données :

- l'**identité de la version au lancement** : numéro, dossier d'où le code
  est réellement chargé, Python, Qt, système, dossier du navire. Deux fois
  déjà, un message d'erreur du bord venait d'une copie précédente restée sur
  le bureau ; la première ligne du journal tranche désormais la question ;
- **tout ce qui part sur la sortie d'erreur**, y compris les traces des
  exceptions non rattrapées et les messages que PySide écrit quand une
  méthode `paint()` tombe — ceux-là ne passent par aucun `except` de Carène ;
- **les messages de Qt** (`qInstallMessageHandler`) ;
- ce que l'application décide de noter elle-même (`noter`).

Ce qu'il n'écrit PAS : aucune donnée de chargement, aucun nom de port,
aucune position. Le journal sert au débogage, pas à l'exploitation — le
journal de bord des points de chargement, lui, est ailleurs (`journal.py`).

Un fichier par jour, les dix derniers gardés. Si rien n'est inscriptible, le
journal se tait : il ne doit jamais empêcher Carène de démarrer.
"""
from __future__ import annotations

import atexit
import datetime
import faulthandler
import os
import platform
import re
import sys
import traceback

GARDER = 10                      # nombre de fichiers de journal conservés
TAILLE_MAX = 5 * 1024 * 1024     # 5 Mo : au-delà, on repart d'un fichier neuf

_fichier = None                  # flux ouvert, ou None si le journal se tait
_chemin = None
_installe = False


# --------------------------------------------------------------- emplacement
def dossier() -> str:
    """Où vivent les journaux : à côté de la configuration.

    Même endroit que `carene.config.json`, donc à côté de l'application sur
    une clé USB et dans le profil utilisateur si l'application est installée
    dans un dossier en lecture seule — c'est le seul endroit dont on soit
    sûr qu'il est inscriptible."""
    from . import app_paths
    return os.path.join(app_paths.DATA_DIR, "journaux")


def chemin() -> str | None:
    """Le fichier de journal en cours, ou None si le journal se tait."""
    return _chemin


def _ouvrir():
    global _fichier, _chemin
    rep = dossier()
    try:
        os.makedirs(rep, exist_ok=True)
        nom = "carene-%s.log" % datetime.date.today().isoformat()
        p = os.path.join(rep, nom)
        # un journal qui a débordé (une boucle de messages Qt, par exemple)
        # ne doit pas remplir le disque du bord
        if os.path.exists(p) and os.path.getsize(p) > TAILLE_MAX:
            os.replace(p, p + ".1")
        _fichier = open(p, "a", encoding="utf-8", errors="replace")
        _chemin = p
    except OSError:
        _fichier = _chemin = None
        return
    _faire_le_menage(rep)


def _faire_le_menage(rep):
    """Ne garde que les `GARDER` journaux les plus récents."""
    try:
        fichiers = sorted(os.path.join(rep, n) for n in os.listdir(rep)
                          if n.startswith("carene-"))
        for vieux in fichiers[:-GARDER]:
            try:
                os.remove(vieux)
            except OSError:
                pass
    except OSError:
        pass


# ------------------------------------------------------------------ écriture
def noter(quoi: str, categorie: str = "info"):
    """Inscrit une ligne au journal. Ne lève jamais : un journal qui empêche
    de travailler ne sert à rien."""
    if _fichier is None:
        return
    try:
        heure = datetime.datetime.now().strftime("%H:%M:%S")
        for ligne in str(quoi).rstrip().splitlines() or [""]:
            _fichier.write(f"{heure} {categorie:<9} {ligne}\n")
        _fichier.flush()
    except Exception:                       # noqa: BLE001 — jamais bloquant
        pass


class _Double:
    """Écrit à la fois sur le flux d'origine et dans le journal.

    C'est la seule façon d'attraper ce que PySide écrit directement sur la
    sortie d'erreur : « Error calling Python override of … paint() » et les
    `RuntimeError` levées dans un slot ne passent par aucun `except` à nous.
    En exécutable gelé sans console, le flux d'origine est `None` : le
    journal devient alors le seul destinataire, et rien n'est perdu."""

    def __init__(self, flux, categorie):
        self.flux = flux
        self.categorie = categorie
        self._reste = ""

    def write(self, texte):
        if self.flux is not None:
            try:
                self.flux.write(texte)
            except Exception:               # noqa: BLE001
                pass
        # on n'inscrit que des lignes entières : une trace arrive morceau
        # par morceau, et une ligne coupée en trois est illisible
        self._reste += texte
        while "\n" in self._reste:
            ligne, self._reste = self._reste.split("\n", 1)
            ligne = _ANSI.sub("", ligne)
            if ligne.strip():
                noter(ligne, self.categorie)
        return len(texte)

    def flush(self):
        if self.flux is not None:
            try:
                self.flux.flush()
            except Exception:               # noqa: BLE001
                pass

    def isatty(self):
        return bool(self.flux is not None and getattr(self.flux, "isatty", bool)())

    def __getattr__(self, nom):
        return getattr(self.flux, nom)


# ------------------------------------------------------------- installation
def entete() -> list[str]:
    """L'identité de ce qui tourne. C'est la première chose à lire quand un
    message d'erreur revient du bord : le dossier dit quelle copie est
    lancée, et deux copies coexistent souvent sur un bureau."""
    from . import __version__
    from . import app_paths
    lignes = [
        "",
        "=" * 72,
        "Carène %s — %s" % (__version__,
                            datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")),
        "  code chargé depuis : %s" % os.path.dirname(os.path.abspath(__file__)),
        "  exécutable gelé    : %s" % ("oui" if getattr(sys, "frozen", False)
                                       else "non (sources)"),
        "  Python             : %s" % sys.version.split()[0],
    ]
    try:
        import PySide6
        from PySide6 import QtCore
        lignes.append("  PySide6 / Qt       : %s / %s"
                      % (PySide6.__version__, QtCore.qVersion()))
    except Exception:                       # noqa: BLE001
        lignes.append("  PySide6            : absent ou illisible")
    lignes.append("  système            : %s %s"
                  % (platform.system(), platform.release()))
    try:
        lignes.append("  données            : %s" % app_paths.DATA_DIR)
        lignes.append("  navire             : %s" % app_paths.ship_folder())
    except Exception:                       # noqa: BLE001
        pass
    lignes.append("=" * 72)
    return lignes


def _sur_exception(genre, valeur, trace):
    texte = "".join(traceback.format_exception(genre, valeur, trace))
    noter("EXCEPTION NON RATTRAPÉE", "erreur")
    noter(texte, "erreur")
    # La trace va aussi à la console, mais par le flux D'ORIGINE : passer par
    # `sys.__excepthook__` la renvoyait dans `sys.stderr`, c'est-à-dire dans
    # le journal une seconde fois — et en couleurs sous Python 3.13+, donc
    # truffée de codes d'échappement illisibles (vu au journal du 17/09).
    console = sys.__stderr__
    if console is not None:
        try:
            console.write(texte)
            console.flush()
        except Exception:                   # noqa: BLE001
            pass


# les codes de couleur du terminal (« ESC[35m »…) n'ont rien à faire dans un
# fichier qu'on lit dans un éditeur de texte
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _fermeture():
    """Dernière ligne d'une session qui s'est terminée normalement. Son
    absence, à la relecture, signe un plantage : c'est ce qui manquait pour
    lire les huit lancements en une heure du 22/09 (fermés, ou tombés ?)."""
    noter("fermeture normale de Carène", "version")


def _sur_message_qt(genre, contexte, message):
    noms = {0: "qt-debug", 1: "qt-warn", 2: "qt-critique",
            3: "qt-fatal", 4: "qt-info"}
    try:
        cat = noms.get(int(genre), "qt")
    except Exception:                       # noqa: BLE001
        cat = "qt"
    ou = ""
    fichier = getattr(contexte, "file", None)
    if fichier:
        ou = " (%s:%s)" % (os.path.basename(fichier),
                           getattr(contexte, "line", "?"))
    noter(str(message) + ou, cat)


def installer(qt=True) -> str | None:
    """Ouvre le journal, écrit l'entête et détourne ce qui doit y arriver.

    Appelé une seule fois, au tout début du lancement — avant la fenêtre,
    pour qu'un plantage à l'ouverture soit noté lui aussi. Rend le chemin du
    journal, ou None s'il n'a pas pu être ouvert."""
    global _installe
    if _installe:
        return _chemin
    _installe = True
    _ouvrir()
    if _fichier is None:
        return None
    for ligne in entete():
        noter(ligne, "version")
    sys.stderr = _Double(sys.stderr, "stderr")
    sys.stdout = _Double(sys.stdout, "sortie")
    sys.excepthook = _sur_exception
    atexit.register(_fermeture)
    # Un plantage NATIF (Qt, pilote graphique) tue le processus sans passer
    # par Python : sans faulthandler, il ne laisse aucune trace. On lui donne
    # le fichier du journal, où il écrit la pile de chaque fil au moment de
    # la chute.
    try:
        faulthandler.enable(file=_fichier, all_threads=True)
    except Exception:                       # noqa: BLE001
        pass
    if qt:
        try:
            from PySide6.QtCore import qInstallMessageHandler
            qInstallMessageHandler(_sur_message_qt)
        except Exception:                   # noqa: BLE001
            pass
    return _chemin


def dernieres_lignes(n=400) -> str:
    """Les `n` dernières lignes du journal en cours — de quoi montrer à
    l'écran ce qu'on demanderait autrement d'aller chercher dans un
    dossier."""
    if not _chemin:
        return "Le journal n'a pas pu être ouvert (dossier non inscriptible)."
    try:
        with open(_chemin, encoding="utf-8", errors="replace") as f:
            lignes = f.readlines()
        return "".join(lignes[-n:])
    except OSError as e:
        return "Journal illisible : %s" % e
