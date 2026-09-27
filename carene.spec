# -*- mode: python ; coding: utf-8 -*-
"""Recette PyInstaller de Carène — `pyinstaller carene.spec` depuis la
racine (PyInstaller installé : `pip install pyinstaller`).

Deux formes, choisies par la variable d'environnement `CARENE_ONEFILE` :

- **dossier** (défaut) : `dist/Carene/Carene.exe` + ses bibliothèques.
  Démarrage quasi immédiat. C'est la forme à installer à bord ;
- **fichier unique** (`CARENE_ONEFILE=1`) : `dist/Carene.exe`, un seul
  fichier qu'on envoie par mail ou qu'on pose sur une clé. Il se déballe dans
  un dossier temporaire à chaque lancement : comptez 10 à 30 s d'attente au
  démarrage. Le navire, lui, reste **à côté de l'exe** — jamais dans le
  temporaire (voir `carene/app_paths.py`).

Le programme n'embarque **aucune donnée de navire** : le dossier `navire/` se
pose à côté de l'exécutable, et se remplace sans reconstruire quoi que ce soit.
"""
import os

ONEFILE = os.environ.get("CARENE_ONEFILE", "") not in ("", "0", "false", "False")
ICONE = "carene/carene.ico" if os.path.exists("carene/carene.ico") else None

# Modules Qt que Carène n'utilise pas. Les exclure divise la taille par deux
# environ. Si un jour l'application se met à en utiliser un, l'exécutable
# tombera au démarrage avec un ImportError explicite : retirer la ligne.
QT_INUTILES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtSerialPort",
    "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSensors",
    "PySide6.QtNetworkAuth", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtUiTools", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech",
]
# Le reste : ce qu'un interpréteur traîne et dont une application de
# stabilité n'a que faire.
AUTRES_INUTILES = [
    "tkinter", "matplotlib", "scipy", "pandas", "PIL", "IPython",
    "pytest", "setuptools", "pip", "sqlite3", "pydoc", "doctest",
]

# La traduction française des boutons standard de Qt (« Fermer », « Annuler »).
# PyInstaller ne l'embarque pas tout seul : sans cette ligne, l'exécutable
# affiche « Close » au milieu d'une interface française.
def _aide():
    """Les pages de l'aide intégrée et leurs captures.

    `carene/aide/*.md` et `carene/aide/images/*` sont des données du LOGICIEL,
    comme la liste UN/LOCODE : `carene/aide_dialog.py` les lit à côté de son
    propre fichier. Sans ces lignes, l'exécutable démarre très bien et
    *Aide › Aide de Carène…* n'affiche plus que « Page introuvable » — et
    personne ne s'en aperçoit avant d'en avoir besoin, à bord.
    `test_aide.py` vérifie que cette recette les embarque.
    """
    entrees = []
    for rep, cible in (("carene/aide", "carene/aide"),
                       ("carene/aide/images", "carene/aide/images")):
        if not os.path.isdir(rep):
            continue
        for nom in sorted(os.listdir(rep)):
            chemin = os.path.join(rep, nom)
            if os.path.isfile(chemin):
                entrees.append((chemin, cible))
    return entrees


def _reglements():
    """La bibliothèque des réglementations de stabilité (D-79) : des données
    du LOGICIEL, lues par `carene/core/reglements.py` à côté de son paquet.
    Sans ces lignes, l'exécutable démarre et ne trouve AUCUNE réglementation —
    `test_bibliotheque.py` vérifie que cette recette les embarque."""
    rep = "carene/reglements"
    if not os.path.isdir(rep):
        return []
    return [(os.path.join(rep, n), rep) for n in sorted(os.listdir(rep))
            if n.endswith(".json")]


def _traduction_qt():
    try:
        from PySide6.QtCore import QLibraryInfo
        d = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        f = os.path.join(d, "qtbase_fr.qm")
        return [(f, "PySide6/Qt/translations")] if os.path.exists(f) else []
    except Exception:
        return []


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    # La liste mondiale des ports (UN/LOCODE) est une donnée du LOGICIEL, pas
    # du navire : `carene/ports.py` la lit à côté de son propre fichier. Sans
    # ces deux lignes, l'exécutable démarre très bien et le champ « Escale » ne
    # propose plus que les ports du navire — l'absence des fichiers est avalée
    # en silence (OSError), personne ne s'aperçoit de rien.
    datas=_traduction_qt() + _aide() + _reglements() + [
        ("carene/donnees/ports_unlocode.csv.gz", "carene/donnees"),
        ("carene/donnees/pays_unlocode.csv.gz", "carene/donnees"),
    ],
    # pymupdf charge sa bibliothèque native à l'import ; PyInstaller la voit,
    # mais on l'inscrit pour que l'absence du module saute aux yeux à la
    # construction plutôt qu'au premier import de PDF à bord.
    # ezdxf, lui, charge ses lecteurs d'entités et ses outils de chemin par
    # nom au premier DXF ouvert : sans ces lignes, l'exécutable démarre très
    # bien et ne sait plus lire un DXF une fois à bord.
    # (pas ezdxf.addons : il tire fonttools et matplotlib pour du texte dont
    # Carène n'a que faire — un fond de plan se décalque, il ne se lit pas)
    # openpyxl : le classeur type du navire (création et import) passe par
    # lui, et il charge ses lecteurs par nom. Sans cette ligne, l'exécutable
    # démarre très bien et « Créer le classeur type à remplir… » échoue à bord
    # sur un ImportError.
    hiddenimports=["pymupdf", "ezdxf", "ezdxf.entities", "ezdxf.path",
                   "ezdxf.recover", "openpyxl", "openpyxl.comments",
                   "openpyxl.styles", "openpyxl.utils"],
    hookspath=[],
    runtime_hooks=[],
    excludes=QT_INUTILES + AUTRES_INUTILES,
    noarchive=False,
)
pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="Carene",
        console=False,          # application graphique : pas de console noire
        icon=ICONE,
        upx=False,              # UPX déclenche des faux positifs antivirus
        strip=False,
    )
else:
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="Carene",
        console=False,
        icon=ICONE,
        upx=False,
        strip=False,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="Carene",
                   upx=False, strip=False)
