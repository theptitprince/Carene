<div align="center">

# Carène — chargement et stabilité

**Aide au chargement et à la stabilité à l'état intact des navires de charge.**

![Version](https://img.shields.io/badge/version-3.6.1-2ea44f)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![PySide6](https://img.shields.io/badge/PySide6-6.6%2B-41CD52?logo=qt&logoColor=white)
![NumPy](https://img.shields.io/badge/NumPy-1.24%2B-013243?logo=numpy&logoColor=white)
![Plateforme](https://img.shields.io/badge/plateforme-Windows-0078D6?logo=windows&logoColor=white)
![Licence](https://img.shields.io/badge/licence-GPL--3.0--or--later-blue)
![Statut](https://img.shields.io/badge/statut-aide%20non%20certifi%C3%A9e-orange)

</div>

---

> [!WARNING]
> **Carène est une aide, ni certifiée ni réglementaire.** Seuls le dossier de stabilité approuvé du navire et
> l'appréciation du capitaine font foi. Les chiffres affichés valent ce que valent les tables du dossier installé
> et les relevés saisis à bord ; toute valeur extrapolée ou approchée est signalée comme telle à l'écran.
> Carène se limite à la stabilité à l'état intact et au positionnement des colis : ni stabilité après avarie,
> ni saisissage, ni ségrégation IMDG.

Carène se tient à côté de l'officier pendant qu'il prépare son chargement :
il pose ses colis sur le plan des cales, relève ses capacités, et lit à tout
moment l'équilibre, la courbe de stabilité et les critères réglementaires que
son navire doit tenir.

Une installation gère un seul navire. Carène est écrite en Python avec
PySide6 ; elle est développée et testée sous Windows, avec Python 3.14.

Version actuelle : 3.6.1 — chaque version a sa
[note de version](https://github.com/theptitprince/Carene/releases), et
l'historique complet des livraisons est dans [LISEZMOI.txt](LISEZMOI.txt).

## Sommaire
- [1. Installation](#1-installation)
- [2. Les fichiers](#2-les-fichiers)
- [3. Lancement](#3-lancement)
- [4. Ce que fait Carène](#4-ce-que-fait-carène)
- [5. L'aide intégrée](#5-laide-intégrée)
- [6. Versions et mises à jour](#6-versions-et-mises-à-jour)
- [7. Signaler un problème](#7-signaler-un-problème)
- [8. Contribuer](#8-contribuer)
- [9. En cas de souci](#9-en-cas-de-souci)
- [10. Licence](#10-licence)

---

## 1. Installation

### Python

Il faut **Python 3.10 ou plus récent** (Carène est développée avec
Python 3.14). Installez-le depuis <https://www.python.org/downloads/> et
cochez **« Add python.exe to PATH »** à l'installation.

Pour vérifier, ouvrez PowerShell et tapez :

```powershell
python --version
```

### Le plus simple : `installer_dependances.bat`

Python installé, double-cliquez **une fois** sur
**`installer_dependances.bat`**, dans le dossier de Carène, sur chaque poste
qui lance Carène depuis les sources. Il :

1. cherche Python (le lanceur `py` d'abord, sinon `python`) ;
2. installe `pip` s'il manque (par `ensurepip`) ;
3. installe ou met à jour les paquets listés dans `requirements.txt` ;
4. refait le contrôle du lancement (`main.py --dependances`) et dit si tout
   est en place.

### À la main

Dans une console ouverte dans le dossier de Carène :

```powershell
python -m pip install -r requirements.txt
```

`requirements.txt` est la seule liste qui fait foi — Carène la relit à chaque
lancement pour vérifier ce qui est installé :

| Bibliothèque | Version minimale | Ce qu'elle apporte |
|---|---|---|
| `PySide6` | 6.6 | l'interface (Qt) |
| `numpy` | 1.24 | les calculs |
| `pymupdf` | 1.24 | la lecture des plans en PDF (fonds de plan) |
| `ezdxf` | 1.1 | la lecture des plans en DXF (fonds de plan) |
| `openpyxl` | 3.1 | le classeur Excel du navire (création et import) |

---

## 2. Les fichiers

Récupérez le dépôt, au choix :

- bouton vert **Code → Download ZIP** sur la page GitHub, puis décompressez
  l'archive dans un dossier ;
- ou, si vous avez git :

```powershell
git clone https://github.com/theptitprince/Carene.git
```

| Fichier | Rôle |
|---|---|
| `main.py` | le point d'entrée : `python main.py`, et les options `--dependances`, `--chemins`, `--sauvegarde` |
| `carene/` | le programme : les fenêtres (PySide6) et, dans `carene/core/`, le moteur de calcul, sans Qt |
| `carene/aide/` | les pages de l'aide intégrée et leurs captures d'écran |
| `carene/reglements/` | les réglementations de stabilité, une par fichier JSON |
| `carene/donnees/` | la liste mondiale des ports et des pays (UN/LOCODE), pour le champ « Escale » |
| `requirements.txt` | les bibliothèques Python nécessaires et leur version minimale |
| `installer_dependances.bat` | installe ou met à jour ces bibliothèques, puis vérifie |
| `carene.spec` | la recette PyInstaller de l'exécutable Windows |
| `LISEZMOI.txt` | l'historique des versions |
| `docs/serveur_mise_a_jour.md` | ce que Carène attend du serveur des mises à jour, et comment le préparer |
| `.github/ISSUE_TEMPLATE/` | le formulaire de signalement des Issues, et le lien vers l'aide |
| `LICENSE` | le texte de la licence (voir [Licence](#10-licence)) |

### Ce que Carène crée à côté d'elle

| Fichier ou dossier | Rôle |
|---|---|
| `navires/<NOM>/` | le dossier du navire : tables, plans, catalogue, journal des points, exports |
| `carene.config.json` | la configuration du poste : emplacement du navire, serveur des mises à jour, réglages |
| `journaux/` | le journal technique, un fichier par jour (`carene-AAAA-MM-JJ.log`), les dix derniers gardés |
| `sauvegardes/` | les sauvegardes du navire (zip) : le dossier proposé par *Navire › Exporter une sauvegarde du navire…*, et celui de `python main.py --sauvegarde` sans nom de fichier |

Ces dossiers sont **les vôtres** : aucun n'est versé au dépôt, et une mise à
jour de Carène ne les touche pas. Le dossier du navire peut vivre ailleurs —
sur une clé ou un disque partagé (NAS), par exemple : déplacez-le à sa
nouvelle place, puis désignez-le par *Navire › Ouvrir un autre dossier de
navire…* (Carène, elle, ne déplace rien). Un exécutable posé dans un dossier
où il ne peut pas écrire (comme `C:\Program Files`) écrit sa configuration,
ses journaux et ses navires dans `%LOCALAPPDATA%\Carene`.

---

## 3. Lancement

Ouvrez PowerShell dans le dossier de Carène et tapez :

```powershell
python main.py
```

(ou `py -3 main.py` si seul le lanceur `py` est installé.)

À chaque lancement, Carène vérifie d'abord ses dépendances ; puis elle
rappelle ce qu'elle est (l'avertissement ci-dessus) et, si le journal du
navire contient déjà des points, demande sur lequel travailler (la question
peut être désactivée).

**Au premier lancement, sans navire**, l'écran d'accueil propose deux
boutons : **Créer le navire…** (la même fenêtre que *Navire › Créer ou
modifier le navire…*) et **Lire d'abord l'aide…**, qui ouvre l'aide droit sur
la page « Recréer le navire depuis un logiciel vierge ». Un navire neuf est
écrit dans `navires/<NOM>/`, à côté du programme ; il n'est jamais versé au
dépôt.

### Les options de la ligne de commande

```powershell
python main.py --dependances
python main.py --chemins
python main.py --sauvegarde
python main.py --sauvegarde chemin\vers\fichier.zip
```

- `--dependances` dit, paquet par paquet, ce qui est installé et ce qui
  manque, puis s'arrête (code de retour 1 s'il manque quelque chose).
- `--chemins` affiche où Carène cherche le navire et écrit sa configuration,
  puis s'arrête : c'est la première chose à demander quand « il ne trouve pas
  mon navire ».
- `--sauvegarde [fichier.zip]` écrit la sauvegarde du navire (le même zip
  que *Navire › Exporter une sauvegarde du navire…*) sans ouvrir la fenêtre,
  par exemple depuis une tâche planifiée du poste. Sans nom de fichier, le zip
  va dans `sauvegardes/`, nommé par le navire et l'instant. Code de retour 1
  si rien n'a pu être écrit.

### Un exécutable Windows

Un exécutable Windows se fabrique avec PyInstaller, depuis la racine du
dépôt :

```powershell
python -m pip install pyinstaller
pyinstaller carene.spec
```

Deux formes, choisies par la variable d'environnement `CARENE_ONEFILE` :

- **dossier** (par défaut) : `dist/Carene/Carene.exe` et ses bibliothèques.
  Démarrage quasi immédiat : c'est la forme à installer à bord ;
- **fichier unique** : `dist/Carene.exe`, un seul fichier à envoyer ou à
  poser sur une clé. Il se déballe dans un dossier temporaire à chaque
  lancement : comptez 10 à 30 s d'attente au démarrage.

```powershell
$env:CARENE_ONEFILE = "1"
pyinstaller carene.spec
```

L'exécutable embarque l'aide intégrée, les réglementations et la liste des
ports, mais **aucune donnée de navire** : le navire reste à côté de l'exe,
jamais dans le dossier temporaire. Le poste de destination n'a besoin ni de
Python ni d'aucune bibliothèque.

---

## 4. Ce que fait Carène

- **Le navire se décrit, il n'est pas programmé.** Tables hydrostatiques,
  pantocarènes, jaugeages, lège, surface au vent, plans des cales : tout
  s'importe à la création du navire (classeur Excel ou CSV), et des **cas de
  référence** du dossier approuvé se rejouent pour prouver que les tables ont
  été bien reprises.
- **Le chargement se pose sur le plan** : colis du catalogue du bord, piles,
  aimantation aux voisins et aux parois, zones interdites, épontilles,
  hauteur libre, charge admissible des ponts, cales IMDG ; un **répartiteur**
  propose une répartition, qu'on garde ou qu'on retouche.
- **Les capacités se relèvent** — sonde, volume ou pourcentage — avec leurs
  carènes liquides ; le **ballastage** cherche la meilleure répartition dans
  les ballasts, et les **tirants d'eau relevés** à la coque se comparent au
  chargement déclaré.
- **La stabilité se lit en continu** : équilibre (tirants d'eau, assiette,
  gîte), GM corrigé des carènes liquides, courbe GZ, critère météo, et les
  critères de chaque réglementation retenue. Un calcul qui sort du domaine
  des tables est annoncé `HORS DOMAINE`, jamais présenté comme un résultat.
- **Les réglementations sont des fichiers de données**
  (`carene/reglements/*.json`) : Code IS 2008 (critères généraux, critère
  météo, navires à passagers, bois en pontée, navires de pêche), BV NR500
  pour les voiliers, ligne de charge. Elles se choisissent selon le profil du
  navire, et se mettent à jour sans reprogrammer.
- **Un journal des points de chargement**, et les documents de l'escale : le
  rapport de stabilité en PDF, les plans cotés des cales, le plan de
  chargement pour les dockers, les feuilles de pointage, les exports tableur
  (CSV).
- **Plusieurs postes, un seul navire** : quand le dossier du navire est sur
  un disque partagé, un seul poste l'ouvre en écriture ; les autres disent
  qui le tient et peuvent le consulter en lecture seule.
- **La sauvegarde du navire tient en un zip** — tables, plans, journal,
  brouillons — écrit par *Navire › Exporter une sauvegarde du navire…* et
  relu par *Navire › Importer une sauvegarde…*, dans cette version ou toute
  version ultérieure ; le navire en place est alors mis de côté, jamais
  effacé.

### Les réglementations livrées

Chaque fichier porte son statut : **vérifiée** (rejouée sur un dossier
approuvé) ou **relue** (relue sur le texte officiel, pas encore rejouée sur un
dossier approuvé).

| Fichier | Réglementation | Statut |
|---|---|---|
| `imo_is2008_a_2_2.json` | Code IS 2008 — critères généraux de stabilité à l'état intact | vérifiée |
| `imo_is2008_a_2_3.json` | Code IS 2008 — critère de roulis et de vent violent (critère météo) | vérifiée |
| `imo_is2008_a_3_1_passagers.json` | Code IS 2008 — navires à passagers : gîte due aux passagers et à la giration | relue |
| `imo_is2008_a_3_3_bois_en_pontee.json` | Code IS 2008 — navires transportant du bois en pontée | relue |
| `imo_is2008_a_3_3_bois_meteo.json` | Code IS 2008 — critère météo, bois en pontée | relue |
| `imo_is2008_b_2_1_peche.json` | Code IS 2008 — navires de pêche : hauteur métacentrique minimale | relue |
| `imo_is2008_b_2_1_peche_meteo.json` | Code IS 2008 — critère météo, navire de pêche de 24 à 45 m | relue |
| `bv_nr500_voilier_gm.json` | BV NR500 — hauteur métacentrique minimale d'un navire à voile | vérifiée |
| `bv_nr500_sous_voile.json` | BV NR500 — stabilité sous voile | vérifiée |
| `ligne_de_charge_1966.json` | Convention sur les lignes de charge — tirant d'eau face à la marque d'été | vérifiée |

---

## 5. L'aide intégrée

L'aide complète est dans le logiciel : *Aide › Aide de Carène…* (touche
**F1**, ou le bouton **Aide** de l'en-tête), une page par écran, avec la
recherche dans toutes les pages à la fois. Ses boutons **PDF…** et
**Imprimer…** sortent la page affichée ou le manuel entier.

| Page | Ce qu'elle couvre |
|---|---|
| Bienvenue dans Carène | ce que le logiciel fait et ne fait pas, la fenêtre principale, les vues, le verdict |
| Premiers pas : une escale de bout en bout | du lancement à l'export, dans l'ordre, geste par geste |
| Les menus, un par un | chaque menu, chaque entrée, sa touche |
| Le point de chargement | le journal : ouvrir, créer, enregistrer, figer un point ; les escales |
| Les capacités : soutes et ballasts | relever une sonde, lire les carènes liquides, le ballastage |
| Le manifeste et le catalogue | ce qu'on embarque : types, lots, ports, cale imposée, matériel du bord |
| Charger à la main | poser, tourner, retirer ; l'aimantation, les épontilles, les refus de pose |
| Le répartiteur automatique | ses réglages et la lecture de son compte rendu |
| La stabilité | tirants d'eau, assiette, gîte, GM, courbe GZ, critères, domaine des tables |
| Les exports et rapports | les documents qui sortent, leur contenu, où ils sont écrits |
| Le navire | créer le navire, importer les tables, décalquer les plans |
| Recréer le navire depuis un logiciel vierge | le parcours complet, du classeur à remplir aux cas de référence |
| Réglages et dépannage | affichage, raccourcis, emplacement des fichiers, journal technique, mises à jour, dépannage |

---

## 6. Versions et mises à jour

Chaque version a sa [note de version](https://github.com/theptitprince/Carene/releases) ;
`LISEZMOI.txt` retrace tout l'historique.

Les postes équipés se mettent à jour depuis le serveur du développeur
(*Aide › Vérifier les mises à jour…*). La vérification se fait aussi au
lancement, en arrière-plan et sans jamais le bloquer (*Aide › Vérifier les
mises à jour au lancement*, coché par défaut) ; sans connexion, une ligne dit
qu'elle n'a pas pu avoir lieu. L'adresse du serveur, et l'identifiant et le
mot de passe si son dossier est protégé, se règlent dans *Aide › Serveur des
mises à jour…* ; le mot de passe est gardé par Windows, jamais dans un
fichier. Tant que l'adresse est en `http://`, l'identifiant et le mot de
passe passent en clair : Carène le dit.

Le zip téléchargé ne porte que le programme. Il est vérifié (sa taille et son
empreinte SHA-256) : **sans empreinte publiée, rien ne s'installe**. Carène
se ferme, l'ancienne version est gardée de côté dans `_ancienne_<version>\`
— de quoi revenir en arrière —, le zip est déplié par-dessus le programme et
Carène se relance ; l'opération est notée dans `journaux\mise_a_jour.log`.
**Le dossier du navire n'est jamais touché**, ni la configuration, ni les
journaux. Comment préparer le serveur :
[docs/serveur_mise_a_jour.md](docs/serveur_mise_a_jour.md).

---

## 7. Signaler un problème

*Aide › Signaler un problème…* pose trois questions (ce que vous faisiez, ce
qui s'est passé, ce que vous attendiez), y joint ce qui tournait (version,
système, navire, point, verdict et, si la case reste cochée, les dernières
lignes du journal technique) et ouvre un nouveau signalement dans les
[Issues](https://github.com/theptitprince/Carene/issues) de ce dépôt — il
faut un compte GitHub, gratuit. Le rapport peut aussi être copié ou
enregistré dans un fichier, pour un poste sans navigateur.

Le dépôt est public : relisez le rapport avant de l'envoyer ; le nom du
navire et le chemin de son dossier y sont masqués par défaut. Qui ouvre un
signalement directement sur GitHub trouve un formulaire qui pose les mêmes
questions.

---

## 8. Contribuer

Carène est un projet personnel, développé au plus près de l'usage à bord.
Les signalements et les idées sont les bienvenus dans les
[Issues](https://github.com/theptitprince/Carene/issues) ; pour une
modification du code, ouvrez d'abord une issue pour en parler.

---

## 9. En cas de souci

**« Il manque à ce poste, pour lancer Carène : … »** — une bibliothèque de
`requirements.txt` manque ou est trop ancienne. Carène le vérifie à chaque
lancement, avant d'ouvrir quoi que ce soit, et donne la commande à lancer.
Double-cliquez `installer_dependances.bat`, ou tapez
`python -m pip install -r requirements.txt` ; `python main.py --dependances`
donne l'état paquet par paquet.

**« Python … est trop ancien pour Carène »** — il faut Python 3.10 ou plus
(voir [Installation](#1-installation)).

**Pas d'accès à Internet** — `pip` ne peut pas télécharger les paquets.
Faites l'installation depuis un poste connecté, ou préparez-y le dossier des
paquets (même version de Python, Windows) :

```powershell
python -m pip download -r requirements.txt -d paquets
```

puis, sur le poste hors ligne, avec ce dossier `paquets` copié à côté :

```powershell
python -m pip install --no-index --find-links paquets -r requirements.txt
```

**Carène ne trouve pas le navire** — `python main.py --chemins` dit où elle
le cherche ; *Navire › Ouvrir un autre dossier de navire…* en désigne un
autre. Si le navire est sur un disque partagé (NAS) qui ne répond pas, Carène
n'ouvre rien à sa place et propose **Réessayer**.

**« Carène est déjà ouvert »** — une seule instance par poste : un second
lancement ramène la fenêtre ouverte au premier plan. Si le navire est ouvert
sur un autre poste, Carène dit lequel et propose de le consulter en lecture
seule, ou de quitter. Si ce poste ne donne plus signe de vie depuis trois
minutes (planté, câble débranché), elle propose aussi de reprendre le
navire — à ne faire que si personne n'y travaille.

**Windows avertit au premier lancement de l'exécutable** — il n'est pas
signé : *Informations complémentaires*, puis *Exécuter quand même*.

Pour le reste : *Aide › Journal technique…* montre ce que Carène a noté, et
la page « Réglages et dépannage » de l'aide intégrée détaille chaque cas.

---

## 10. Licence

Carène est un **logiciel libre**, distribué sous la licence
**GNU General Public License, version 3 ou ultérieure** (GPL-3.0-or-later).

Copyright © 2026 ETDEL.

Concrètement, vous pouvez utiliser le programme librement, l'étudier, le
modifier et le redistribuer — à condition que toute version redistribuée,
modifiée ou non, reste sous la même licence, avec son code source et la
mention de copyright. Le programme est fourni **sans aucune garantie** :
Carène vous aide à préparer le chargement, elle ne remplace ni le dossier de
stabilité approuvé du navire ni l'appréciation du capitaine.

Le texte intégral de la licence est dans le fichier [`LICENSE`](LICENSE) du
dépôt et sur <https://www.gnu.org/licenses/gpl-3.0.html>. L'en-tête de
`carene/__init__.py` porte la mention de licence, que la fenêtre
*Aide › À propos…* rappelle.

---

*Carène — ETDEL 2026 — GPL-3.0-or-later*
