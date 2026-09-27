# -*- coding: utf-8 -*-
"""Les dépendances de Carène : les vérifier avant de lancer quoi que ce soit.

Le bord (21/09/2026) : « Un .bat pour installer les dépendances
automatiquement ? Un check des dépendances au lancement d'ailleurs ? »

Sans ce contrôle, un poste où il manque `pymupdf` démarre, ouvre le navire,
et tombe une heure plus tard sur un `ModuleNotFoundError` en exportant le
rapport — ou, pire, ne démarre pas du tout avec vingt lignes de traceback
que personne à bord ne sait lire. Ici : on lit `requirements.txt` (la seule
liste qui fait foi — pas une copie dans le code), on regarde quel paquet
manque ou est trop ancien, et on le dit en une phrase, avec la commande à
lancer. Le tout SANS importer Qt : c'est justement PySide6 qui peut manquer.

Rapide : `importlib.util.find_spec` ne charge pas le module, et
`importlib.metadata.version` lit une petite fiche. Le contrôle ne coûte
pas un dixième de seconde au lancement.
"""
import importlib.metadata
import importlib.util
import os
import re
import sys

# Le nom du paquet (pip) et le nom du module (import) ne coïncident pas
# toujours : c'est la seule chose que le code a besoin de savoir en propre.
MODULES = {"pymupdf": "pymupdf", "PySide6": "PySide6", "numpy": "numpy",
           "ezdxf": "ezdxf", "openpyxl": "openpyxl"}
REQUIREMENTS = "requirements.txt"
COMMANDE_WINDOWS = "installer_dependances.bat"
COMMANDE_PIP = "python -m pip install -r requirements.txt"


class Manque:
    """Un paquet qui manque, ou qui est trop ancien."""

    def __init__(self, paquet, module, requis="", present="", motif=""):
        self.paquet, self.module = paquet, module
        self.requis, self.present, self.motif = requis, present, motif

    def __str__(self):
        if self.motif == "absent":
            return f"{self.paquet} (absent)"
        if self.motif == "trop ancien":
            return f"{self.paquet} (version {self.present}, il faut {self.requis})"
        return f"{self.paquet} ({self.motif})"


def lire_requirements(chemin=None):
    """`[(paquet, version minimale ou "")]`, lu dans requirements.txt."""
    chemin = chemin or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                    REQUIREMENTS)
    out = []
    try:
        with open(chemin, encoding="utf-8") as f:
            lignes = f.read().splitlines()
    except OSError:
        return out
    for ligne in lignes:
        ligne = ligne.split("#", 1)[0].strip()
        if not ligne or ligne.startswith("-"):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*(?:(>=|==|~=)\s*([0-9][0-9A-Za-z.]*))?", ligne)
        if not m:
            continue
        paquet, version = m.group(1), m.group(3)
        out.append((paquet, version or ""))
    return out


def _version_tuple(v):
    parts = []
    for morceau in re.split(r"[.\-+]", str(v)):
        m = re.match(r"^\d+", morceau)
        if not m:
            break
        parts.append(int(m.group(0)))
    return tuple(parts) or (0,)


def verifier(chemin_requirements=None):
    """Les manques, dans l'ordre de requirements.txt. Vide = tout est là."""
    manques = []
    for paquet, minimum in lire_requirements(chemin_requirements):
        module = MODULES.get(paquet, paquet.replace("-", "_"))
        try:
            present = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            present = False
        if not present:
            manques.append(Manque(paquet, module, minimum, "", "absent"))
            continue
        if not minimum:
            continue
        try:
            version = importlib.metadata.version(paquet)
        except importlib.metadata.PackageNotFoundError:
            # le module est là mais pas sa fiche (installation à la main) :
            # on ne peut pas juger la version, on laisse passer
            continue
        if _version_tuple(version) < _version_tuple(minimum):
            manques.append(Manque(paquet, module, minimum, version, "trop ancien"))
    return manques


def python_trop_vieux(minimum=(3, 10)):
    return sys.version_info[:2] < minimum


def message(manques):
    """Ce qu'on dit au bord — une phrase, la commande, pas de traceback."""
    if python_trop_vieux():
        tete = (f"Python {sys.version_info.major}.{sys.version_info.minor} est trop ancien "
                "pour Carène : il faut Python 3.10 ou plus (python.org, cochez « Add "
                "python.exe to PATH »).\n\n")
    else:
        tete = ""
    if manques:
        tete += ("Il manque à ce poste, pour lancer Carène :\n  - "
                 + "\n  - ".join(str(m) for m in manques) + "\n\n")
    tete += ("Pour tout installer d'un coup : double-cliquez "
             f"{COMMANDE_WINDOWS} (Windows), ou tapez dans une console, dans le "
             f"dossier de Carène :\n    {COMMANDE_PIP}")
    return tete


def rapport():
    """`--dependances` : l'état de chaque paquet, ligne par ligne."""
    lignes = [f"Python {sys.version.split()[0]} — {sys.executable}"]
    for paquet, minimum in lire_requirements():
        module = MODULES.get(paquet, paquet.replace("-", "_"))
        try:
            version = importlib.metadata.version(paquet)
        except importlib.metadata.PackageNotFoundError:
            version = ""
        present = importlib.util.find_spec(module) is not None
        if not present:
            etat = "ABSENT"
        elif minimum and version and _version_tuple(version) < _version_tuple(minimum):
            etat = f"TROP ANCIEN ({version} < {minimum})"
        else:
            etat = f"ok ({version or 'version inconnue'})"
        lignes.append(f"  {paquet:<10} {etat}" + (f"   (il faut >= {minimum})" if minimum else ""))
    return "\n".join(lignes)


def avertir(texte, titre="Carène — dépendances manquantes"):
    """Le message, là où le bord peut le voir : une boîte Windows (sans Qt,
    qui peut manquer), et toujours la console.

    Hors écran (`QT_QPA_PLATFORM=offscreen`, comme dans les tests), pas de
    boîte : `MessageBoxW` attend un clic qui ne viendra jamais, et c'est un
    lancement de `main.py` qui reste suspendu — la console suffit."""
    print(texte, file=sys.stderr)
    if os.name == "nt" and os.environ.get("QT_QPA_PLATFORM", "").lower() != "offscreen":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, texte, titre, 0x10)   # MB_ICONERROR
        except Exception:
            pass
