<div align="center">

# Carène — loading and stability

**An aid to loading and intact stability for cargo ships.**

![Version](https://img.shields.io/badge/version-3.6.1-2ea44f)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![PySide6](https://img.shields.io/badge/PySide6-6.6%2B-41CD52?logo=qt&logoColor=white)
![NumPy](https://img.shields.io/badge/NumPy-1.24%2B-013243?logo=numpy&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows-0078D6?logo=windows&logoColor=white)
![License](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)
![Status](https://img.shields.io/badge/status-uncertified%20aid-orange)

</div>

[Français](README.md) · **English**

> The program's interface is in French; its labels are quoted below as they appear on screen.

---

> [!WARNING]
> **Carène is an aid, neither certified nor regulatory.** Only the ship's approved stability booklet and
> the master's judgment are authoritative. The figures displayed are only as good as the tables of the
> installed ship folder and the readings entered on board; any extrapolated or approximate value is flagged
> as such on screen. Carène is limited to intact stability and the positioning of cargo items: no damage
> stability, no lashing, no IMDG segregation.

Carène stands beside the officer while they prepare the loading:
they place the cargo items on the hold plan, take the tank readings, and can
read at any time the equilibrium, the stability curve and the regulatory
criteria the ship must meet.

One installation handles a single ship. Carène is written in Python with
PySide6; it is developed and tested on Windows, with Python 3.14.

Current version: 3.6.1 — each version has its
[release notes](https://github.com/theptitprince/Carene/releases), and
the complete release history is in [LISEZMOI.txt](LISEZMOI.txt) (in French).

## Contents
- [1. Installation](#1-installation)
- [2. The files](#2-the-files)
- [3. Launching](#3-launching)
- [4. What Carène does](#4-what-carène-does)
- [5. The built-in help](#5-the-built-in-help)
- [6. Versions and updates](#6-versions-and-updates)
- [7. Reporting a problem](#7-reporting-a-problem)
- [8. Contributing](#8-contributing)
- [9. If something goes wrong](#9-if-something-goes-wrong)
- [10. License](#10-license)

---

## 1. Installation

### Python

You need **Python 3.10 or later** (Carène is developed with
Python 3.14). Install it from <https://www.python.org/downloads/> and
check **"Add python.exe to PATH"** during installation.

To check, open PowerShell and type:

```powershell
python --version
```

### The simplest way: `installer_dependances.bat`

With Python installed, double-click **`installer_dependances.bat`**, in the
Carène folder, **once** on each workstation that runs Carène from the
sources. It:

1. looks for Python (the `py` launcher first, otherwise `python`);
2. installs `pip` if it is missing (via `ensurepip`);
3. installs or updates the packages listed in `requirements.txt`;
4. reruns the startup check (`main.py --dependances`) and tells you whether
   everything is in place.

### By hand

In a console opened in the Carène folder:

```powershell
python -m pip install -r requirements.txt
```

`requirements.txt` is the only authoritative list — Carène rereads it at every
launch to check what is installed:

| Library | Minimum version | What it provides |
|---|---|---|
| `PySide6` | 6.6 | the interface (Qt) |
| `numpy` | 1.24 | the calculations |
| `pymupdf` | 1.24 | reading plans in PDF (plan backgrounds) |
| `ezdxf` | 1.1 | reading plans in DXF (plan backgrounds) |
| `openpyxl` | 3.1 | the ship's Excel workbook (creation and import) |

---

## 2. The files

Get the repository, either:

- with the green **Code → Download ZIP** button on the GitHub page, then unzip
  the archive into a folder;
- or, if you have git:

```powershell
git clone https://github.com/theptitprince/Carene.git
```

| File | Role |
|---|---|
| `main.py` | the entry point: `python main.py`, and the options `--dependances`, `--chemins`, `--sauvegarde` |
| `carene/` | the program: the windows (PySide6) and, in `carene/core/`, the calculation engine, without Qt |
| `carene/aide/` | the pages of the built-in help and their screenshots |
| `carene/reglements/` | the stability regulations, one per JSON file |
| `carene/donnees/` | the worldwide list of ports and countries (UN/LOCODE), for the "Escale" (port of call) field |
| `requirements.txt` | the Python libraries required and their minimum version |
| `installer_dependances.bat` | installs or updates these libraries, then checks |
| `carene.spec` | the PyInstaller recipe for the Windows executable |
| `LISEZMOI.txt` | the version history (in French) |
| `docs/serveur_mise_a_jour.md` | what Carène expects from the update server, and how to prepare it (in French) |
| `.github/ISSUE_TEMPLATE/` | the form for reporting Issues, and the link to the help |
| `LICENSE` | the text of the license (see [License](#10-license)) |

### What Carène creates alongside itself

| File or folder | Role |
|---|---|
| `navires/<NOM>/` | the ship folder: tables, plans, catalog, log of loading conditions, exports |
| `carene.config.json` | the workstation configuration: location of the ship, update server, settings |
| `journaux/` | the technical log, one file per day (`carene-AAAA-MM-JJ.log`), the last ten kept |
| `sauvegardes/` | the ship backups (zip): the folder offered by *Navire › Exporter une sauvegarde du navire…* (Ship › Export a backup of the ship…), and the one used by `python main.py --sauvegarde` without a file name |

These folders are **yours**: none of them is committed to the repository, and
an update of Carène does not touch them. The ship folder can live elsewhere —
on a USB stick or a shared drive (NAS), for example: move it to its new
place, then point to it with *Navire › Ouvrir un autre dossier de
navire…* (Ship › Open another ship folder…); Carène itself moves nothing. An
executable placed in a folder where it cannot write (such as
`C:\Program Files`) writes its configuration, its logs and its ships to
`%LOCALAPPDATA%\Carene`.

---

## 3. Launching

Open PowerShell in the Carène folder and type:

```powershell
python main.py
```

(or `py -3 main.py` if only the `py` launcher is installed.)

At every launch, Carène first checks its dependencies; then it reminds you
what it is (the warning above) and, if the ship's log already contains
loading conditions, asks which one to work on (this question can be turned
off).

**On the first launch, with no ship**, the welcome screen offers two
buttons: **Créer le navire…** (Create the ship…), the same window as
*Navire › Créer ou modifier le navire…* (Ship › Create or edit the ship…),
and **Lire d'abord l'aide…** (Read the help first…), which opens the help
directly at the page "Recréer le navire depuis un logiciel vierge"
(Recreating the ship from a blank installation). A new ship is written to
`navires/<NOM>/`, next to the program; it is never committed to the
repository.

### The command-line options

```powershell
python main.py --dependances
python main.py --chemins
python main.py --sauvegarde
python main.py --sauvegarde chemin\vers\fichier.zip
```

- `--dependances` tells you, package by package, what is installed and what
  is missing, then exits (exit code 1 if anything is missing).
- `--chemins` shows where Carène looks for the ship and writes its
  configuration, then exits: it is the first thing to ask for when "it can't
  find my ship".
- `--sauvegarde [fichier.zip]` writes the ship backup (the same zip as
  *Navire › Exporter une sauvegarde du navire…*) without opening the window,
  for example from a scheduled task on the workstation. Without a file name,
  the zip goes into `sauvegardes/`, named after the ship and the date and
  time. Exit code 1 if nothing could be written.

### A Windows executable

A Windows executable is built with PyInstaller, from the root of the
repository:

```powershell
python -m pip install pyinstaller
pyinstaller carene.spec
```

Two forms, chosen by the `CARENE_ONEFILE` environment variable:

- **folder** (the default): `dist/Carene/Carene.exe` and its libraries.
  Almost immediate startup: this is the form to install on board;
- **single file**: `dist/Carene.exe`, a single file to send or to put on a
  USB stick. It unpacks itself into a temporary folder at every launch:
  expect a 10 to 30 s wait at startup.

```powershell
$env:CARENE_ONEFILE = "1"
pyinstaller carene.spec
```

The executable embeds the built-in help, the regulations and the list of
ports, but **no ship data**: the ship stays next to the exe, never in the
temporary folder. The target workstation needs neither Python nor any
library.

---

## 4. What Carène does

- **The ship is described, not programmed.** Hydrostatic tables, cross
  curves, tank sounding tables, lightship, windage area, hold plans:
  everything is imported when the ship is created (Excel workbook or CSV),
  and **reference cases** from the approved booklet are replayed to prove
  that the tables have been transcribed correctly.
- **The loading is laid out on the plan**: cargo items from the ship's
  catalog, stacks, snapping to neighboring items and to the hold sides, no-go
  zones, pillars, clear height, permissible deck loads, IMDG holds; an
  **automatic stower** proposes an arrangement, which you keep or adjust.
- **Tanks are read** — by sounding, volume or percentage — with their free
  surface effects; **ballasting** looks for the best distribution across the
  ballast tanks, and the **drafts read** on the hull are compared with the
  declared loading.
- **Stability is read continuously**: equilibrium (drafts, trim, heel), GM
  corrected for free surface effects, GZ curve, weather criterion, and the
  criteria of each selected regulation. A calculation that falls outside the
  range of the tables is flagged `HORS DOMAINE` (out of range), never
  presented as a result.
- **Regulations are data files**
  (`carene/reglements/*.json`): the 2008 IS Code (general criteria, weather
  criterion, passenger ships, timber deck cargoes, fishing vessels), BV NR500
  for sailing vessels, load line. They are selected according to the ship's
  profile, and are updated without reprogramming.
- **A log of loading conditions**, and the port call documents: the
  stability report in PDF, the dimensioned hold plans, the stowage plan for
  the stevedores, the tally sheets, the spreadsheet exports (CSV).
- **Several workstations, one ship**: when the ship folder is on a shared
  drive, only one workstation opens it for writing; the others say who holds
  it and can view it read-only.
- **The ship backup fits in one zip** — tables, plans, log, draft stowage
  plans — written by *Navire › Exporter une sauvegarde du navire…* and read
  back by *Navire › Importer une sauvegarde…* (Ship › Import a backup…), in
  this version or any later version; the ship in place is then set aside,
  never deleted.

### The regulations supplied

Each file carries its status: **vérifiée** (verified: replayed against an
approved booklet) or **relue** (reviewed: checked against the official text,
not yet replayed against an approved booklet).

| File | Regulation | Status |
|---|---|---|
| `imo_is2008_a_2_2.json` | Code IS 2008 — critères généraux de stabilité à l'état intact (2008 IS Code — general intact stability criteria) | vérifiée |
| `imo_is2008_a_2_3.json` | Code IS 2008 — critère de roulis et de vent violent (critère météo) (2008 IS Code — severe wind and rolling criterion, i.e. weather criterion) | vérifiée |
| `imo_is2008_a_3_1_passagers.json` | Code IS 2008 — navires à passagers : gîte due aux passagers et à la giration (2008 IS Code — passenger ships: heel due to passengers and to turning) | relue |
| `imo_is2008_a_3_3_bois_en_pontee.json` | Code IS 2008 — navires transportant du bois en pontée (2008 IS Code — ships carrying timber deck cargoes) | relue |
| `imo_is2008_a_3_3_bois_meteo.json` | Code IS 2008 — critère météo, bois en pontée (2008 IS Code — weather criterion, timber deck cargo) | relue |
| `imo_is2008_b_2_1_peche.json` | Code IS 2008 — navires de pêche : hauteur métacentrique minimale (2008 IS Code — fishing vessels: minimum metacentric height) | relue |
| `imo_is2008_b_2_1_peche_meteo.json` | Code IS 2008 — critère météo, navire de pêche de 24 à 45 m (2008 IS Code — weather criterion, fishing vessel of 24 to 45 m) | relue |
| `bv_nr500_voilier_gm.json` | BV NR500 — hauteur métacentrique minimale d'un navire à voile (BV NR500 — minimum metacentric height of a sailing vessel) | vérifiée |
| `bv_nr500_sous_voile.json` | BV NR500 — stabilité sous voile (BV NR500 — stability under sail) | vérifiée |
| `ligne_de_charge_1966.json` | Convention sur les lignes de charge — tirant d'eau face à la marque d'été (Load Line Convention — draft against the summer mark) | vérifiée |

---

## 5. The built-in help

The complete help is inside the software: *Aide › Aide de Carène…*
(Help › Carène Help…), also opened with the **F1** key or the **Aide** (Help)
button in the header; one page per screen, with search across all the pages
at once. Its **PDF…** and **Imprimer…** (Print…) buttons output the displayed
page or the whole manual.

| Page | What it covers |
|---|---|
| Bienvenue dans Carène (Welcome to Carène) | what the software does and does not do, the main window, the views, the verdict |
| Premiers pas : une escale de bout en bout (Getting started: a port call from start to finish) | from launch to export, in order, step by step |
| Les menus, un par un (The menus, one by one) | each menu, each entry, its key |
| Le point de chargement (The loading condition) | the log: open, create, save, freeze a loading condition; the port calls |
| Les capacités : soutes et ballasts (Tanks: bunkers and ballast) | taking a sounding, reading the free surface effects, ballasting |
| Le manifeste et le catalogue (The manifest and the catalog) | what goes on board: types, lots, ports, assigned hold, ship's equipment |
| Charger à la main (Loading by hand) | placing, rotating, removing; snapping, pillars, refused placements |
| Le répartiteur automatique (The automatic stower) | its settings and how to read its report |
| La stabilité (Stability) | drafts, trim, heel, GM, GZ curve, criteria, range of the tables |
| Les exports et rapports (Exports and reports) | the documents produced, their contents, where they are written |
| Le navire (The ship) | creating the ship, importing the tables, tracing the plans |
| Recréer le navire depuis un logiciel vierge | the complete process, from the workbook to fill in to the reference cases |
| Réglages et dépannage (Settings and troubleshooting) | display, shortcuts, file locations, technical log, updates, troubleshooting |

---

## 6. Versions and updates

Each version has its [release notes](https://github.com/theptitprince/Carene/releases);
`LISEZMOI.txt` traces the whole history.

Workstations running Carène update from the developer's server
(*Aide › Vérifier les mises à jour…* [Help › Check for updates…]). The check
also runs at launch, in the background and without ever holding it up
(*Aide › Vérifier les mises à jour au lancement* [Help › Check for updates at
launch], checked by default); without a connection, a line says that it could
not take place. The server address, and the user name and password if its
folder is protected, are set in *Aide › Serveur des mises à jour…*
(Help › Update server…); the password is kept by Windows, never in a file.
As long as the address starts with `http://`, the user name and password
travel in clear text: Carène says so.

The downloaded zip carries only the program. It is verified (its size and
its SHA-256 hash): **without a published hash, nothing is installed**. Carène
closes, the old version is kept aside in `_ancienne_<version>\` — so you can
go back —, the zip is unpacked over the program and Carène restarts; the
operation is recorded in `journaux\mise_a_jour.log`.
**The ship folder is never touched**, and neither are the configuration
and the logs. How to prepare the server:
[docs/serveur_mise_a_jour.md](docs/serveur_mise_a_jour.md) (in French).

---

## 7. Reporting a problem

*Aide › Signaler un problème…* (Help › Report a problem…) asks three
questions (what you were doing, what happened, what you expected), attaches
what was running (version, system, ship, loading condition, verdict and, if
the box stays checked, the last lines of the technical log) and opens a new
report in the [Issues](https://github.com/theptitprince/Carene/issues) of
this repository — a GitHub account, which is free, is required. The report
can also be copied or saved to a file, for a workstation without a browser.

The repository is public: reread the report before sending it; the ship's
name and the path of its folder are masked in it by default. Anyone who
opens a report directly on GitHub finds a form that asks the same
questions.

---

## 8. Contributing

Carène is a personal project, developed as close as possible to use on board.
Reports and ideas are welcome in the
[Issues](https://github.com/theptitprince/Carene/issues); for a
change to the code, open an issue first to discuss it.

---

## 9. If something goes wrong

**"Il manque à ce poste, pour lancer Carène : …"** (to start Carène, this
workstation is missing: …) — a library from `requirements.txt` is missing or
too old. Carène checks this at every launch, before opening anything, and
gives the command to run. Double-click `installer_dependances.bat`, or type
`python -m pip install -r requirements.txt`; `python main.py --dependances`
gives the status package by package.

**"Python … est trop ancien pour Carène"** (Python … is too old for Carène) —
you need Python 3.10 or later (see [Installation](#1-installation)).

**No Internet access** — `pip` cannot download the packages. Do the
installation from a connected workstation, or prepare the packages folder
there (same version of Python, Windows):

```powershell
python -m pip download -r requirements.txt -d paquets
```

then, on the offline workstation, with this `paquets` folder copied alongside:

```powershell
python -m pip install --no-index --find-links paquets -r requirements.txt
```

**Carène cannot find the ship** — `python main.py --chemins` tells you where
it looks for it; *Navire › Ouvrir un autre dossier de navire…* points to
another one. If the ship is on a shared drive (NAS) that does not respond,
Carène opens nothing in its place and offers **Réessayer** (Retry).

**"Carène est déjà ouvert"** (Carène is already open) — one instance per
workstation: a second launch brings the open window to the front. If the
ship is open on another workstation, Carène says which one and offers to
view it read-only, or to quit. If that workstation has shown no sign of life
for three minutes (crashed, cable unplugged), it also offers to take over
the ship — to be done only if nobody is working on it.

**Windows warns on the first launch of the executable** — it is not
signed: *More info*, then *Run anyway* (*Informations complémentaires*, then
*Exécuter quand même* on a French-language Windows).

For everything else: *Aide › Journal technique…* (Help › Technical log…)
shows what Carène has recorded, and the "Réglages et dépannage" page of the
built-in help details each case.

---

## 10. License

Carène is **free software**, distributed under the
**GNU General Public License, version 3 or later** (GPL-3.0-or-later).

Copyright © 2026 ETDEL.

In practice, you may use the program freely, study it, modify it and
redistribute it — provided that any redistributed version, modified or not,
remains under the same license, with its source code and the copyright
notice. The program is provided **without any warranty**: Carène helps you
prepare the loading; it replaces neither the ship's approved stability
booklet nor the master's judgment.

The full text of the license is in the [`LICENSE`](LICENSE) file of the
repository and at <https://www.gnu.org/licenses/gpl-3.0.html>. The header of
`carene/__init__.py` carries the license notice, which the
*Aide › À propos…* (Help › About…) window repeats.

---

*Carène — ETDEL 2026 — GPL-3.0-or-later*
