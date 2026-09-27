# -*- coding: utf-8 -*-
"""Emplacement du navire — l'application n'en gère qu'un seul.

Carène est mono-navire par conception : une installation = un navire. Il n'y a
donc pas de bibliothèque ni de sélecteur de navire. Le dossier du navire est
fixe (`navire/` à côté de l'application) ; il reste déplaçable — sur un disque
partagé, par exemple — via `set_ship_folder`, l'emplacement retenu étant
mémorisé dans `carene.config.json`.

Pour changer de navire, on supprime celui en place (`delete_ship`) puis on en
crée un nouveau.
"""
from __future__ import annotations
from .ecriture import ecriture_atomique

import json
import os
import shutil
import sys
import time


def _dossier_application():
    """Dossier « à côté de l'application », au sens de l'utilisateur.

    En exécutable gelé (PyInstaller), le code vit dans un dossier temporaire
    (`sys._MEIPASS`) recréé et effacé à chaque lancement : y placer le navire
    et la configuration reviendrait à les perdre en quittant. C'est alors le
    dossier de l'**exécutable** qui fait référence — celui que l'utilisateur
    voit, dans lequel il posera son dossier `navire/`.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _inscriptible(dossier):
    """Peut-on vraiment écrire ici ? On essaie, on ne devine pas.

    `os.access(..., W_OK)` ment sous Windows (il ne regarde que l'attribut
    « lecture seule », pas les ACL de `C:\\Program Files`)."""
    temoin = os.path.join(dossier, ".carene-ecriture")
    try:
        with open(temoin, "w"):
            pass
        os.remove(temoin)
        return True
    except OSError:
        return False


def _dossier_donnees(app_dir):
    """Où vivent la configuration et, par défaut, le navire.

    À côté de l'application — c'est ce qu'on veut à bord : une clé USB ou un
    disque partagé se déplace d'un bloc. Si ce dossier n'est pas inscriptible
    (installation dans `C:\\Program Files`), on se rabat sur le profil de
    l'utilisateur plutôt que d'échouer en silence à enregistrer."""
    if not getattr(sys, "frozen", False) or _inscriptible(app_dir):
        return app_dir
    base = (os.environ.get("LOCALAPPDATA")
            or os.environ.get("XDG_DATA_HOME")
            or os.path.join(os.path.expanduser("~"), ".local", "share"))
    dossier = os.path.join(base, "Carene")
    try:
        os.makedirs(dossier, exist_ok=True)
    except OSError:
        return app_dir
    return dossier


APP_DIR = _dossier_application()
DATA_DIR = _dossier_donnees(APP_DIR)
CONFIG_FILE = os.path.join(DATA_DIR, "carene.config.json")
DEFAULT_FOLDER = os.path.join(DATA_DIR, "navire")
# Les tests (et un poste qui le souhaite) détournent la configuration vers un
# autre fichier : sans cela, chaque test hors écran écrivait son navire jetable
# dans le vrai carene.config.json de l'installation.
ENV_CONFIG = "CARENE_CONFIG"
_config_file_force = None

MANIFEST = "navire.json"
GEOMETRY = "geometrie.json"

# explication du dernier choix de `ship_folder()` quand il n'a pas pu suivre
# la configuration (dossier disparu) : la fenêtre principale l'affiche
DERNIER_MESSAGE = ""
# Le dossier configuré, quand le DISQUE ou le PARTAGE qui le porte ne répond
# pas (NAS pas encore monté, Wi-Fi coupé). "" sinon. Voir `ship_folder`.
NAVIRE_INJOIGNABLE = ""


def _racine_joignable(chemin: str) -> bool:
    """Le disque ou le partage réseau qui porte `chemin` répond-il ?

    « Injoignable » n'est pas « disparu » : un NAS pas encore monté au
    démarrage du poste, un lecteur réseau déconnecté, un Wi-Fi coupé. Le
    dossier est toujours là — c'est le chemin pour y aller qui manque. Un
    chemin sans lecteur ni partage (« /home/… ») est réputé joignable : on
    ne sait pas en juger."""
    lecteur, _reste = os.path.splitdrive(chemin)
    if not lecteur:
        return True
    if lecteur.startswith(("\\\\", "//")):
        racine = lecteur                    # \\serveur\partage
    else:
        racine = lecteur + os.sep           # D:\
    try:
        return os.path.isdir(racine)
    except OSError:
        return False


def config_file() -> str:
    """Le fichier de configuration en vigueur : celui imposé par
    `set_config_file`, sinon la variable d'environnement, sinon le défaut."""
    return _config_file_force or os.environ.get(ENV_CONFIG) or CONFIG_FILE


def set_config_file(path: str | None):
    """Détourne la configuration (None : retour au défaut)."""
    global _config_file_force
    _config_file_force = os.path.abspath(path) if path else None


def _read_config():
    try:
        with open(config_file(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write_config(cfg):
    try:
        with ecriture_atomique(config_file()) as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
    except OSError:
        pass          # emplacement non inscriptible : on garde le défaut


# Suffixe du navire D'EXEMPLE livré avec l'application. Depuis la v2.15, la
# livraison ne contient plus `navires/<NOM>/` — c'est le dossier du bord,
# qu'une mise à jour décompressée par-dessus écrasait — mais
# `navires/<NOM>.exemple/`, que l'application ne lit jamais directement :
# au premier lancement d'une installation vierge, elle le COPIE en
# `navires/<NOM>/` (voir `installer_navire_exemple`), et ne le regarde plus.
SUFFIXE_EXEMPLE = ".exemple"
DERNIER_MESSAGE_EXEMPLE = ""


def _navire_livre():
    """Le navire livré avec l'application, s'il y en a exactement un dans
    `navires/` à côté d'elle (le navire d'exemple dans la livraison v2.3). Les dossiers
    `*.exemple` ne comptent pas : ce sont des modèles à copier, pas des
    navires à ouvrir."""
    for base in (DATA_DIR, APP_DIR):
        rep = os.path.join(base, "navires")
        if not os.path.isdir(rep):
            continue
        candidats = [os.path.join(rep, n) for n in sorted(os.listdir(rep))
                     if os.path.exists(os.path.join(rep, n, MANIFEST))
                     and not n.endswith(SUFFIXE_EXEMPLE)]
        if len(candidats) == 1:
            return candidats[0]
    return None


def navires_exemple():
    """Les dossiers `navires/<NOM>.exemple/` livrés avec l'application."""
    out = []
    # DATA_DIR et APP_DIR sont souvent le même dossier : on ne compte pas
    # deux fois le même exemple
    for base in dict.fromkeys((DATA_DIR, APP_DIR)):
        rep = os.path.join(base, "navires")
        if not os.path.isdir(rep):
            continue
        for n in sorted(os.listdir(rep)):
            if n.endswith(SUFFIXE_EXEMPLE) and os.path.exists(
                    os.path.join(rep, n, MANIFEST)):
                out.append(os.path.join(rep, n))
    return out


def installer_navire_exemple():
    """Première installation : copie le navire d'exemple en vrai navire.

    Seulement si l'installation est VIERGE — aucun navire configuré ni
    trouvé — et qu'un seul exemple est livré. Un `navires/<NOM>/` déjà là
    (celui du bord, avec son journal et ses conditions) n'est jamais touché,
    ni comparé, ni « mis à jour » : c'est tout l'objet de la manœuvre. Rend
    le dossier créé, ou None si rien n'a été fait ; `DERNIER_MESSAGE_EXEMPLE`
    dit ce qui s'est passé pour le journal technique."""
    global DERNIER_MESSAGE_EXEMPLE
    DERNIER_MESSAGE_EXEMPLE = ""
    if ship_exists(ship_folder()):
        return None
    exemples = navires_exemple()
    if len(exemples) != 1:
        return None
    src = exemples[0]
    dest = src[:-len(SUFFIXE_EXEMPLE)]
    if os.path.exists(dest):
        return None
    try:
        shutil.copytree(src, dest)
    except OSError as e:
        DERNIER_MESSAGE_EXEMPLE = (f"Le navire d'exemple {src} n'a pas pu être "
                                   f"copié en {dest} : {e}")
        return None
    set_ship_folder(dest)
    DERNIER_MESSAGE_EXEMPLE = (
        f"Première installation : le navire d'exemple a été copié de {src} vers "
        f"{dest}. Ce dossier est désormais le vôtre — une mise à jour de "
        "Carène ne le touchera plus.")
    return dest


def ship_folder() -> str:
    """Dossier de l'unique navire de cette installation.

    Dans l'ordre : le dossier choisi (« Navire → Ouvrir un autre dossier de navire… »),
    puis `navire/` à côté de l'application, puis le navire livré dans
    `navires/` s'il est seul — c'est ainsi que le navire d'exemple s'ouvre au premier
    lancement sans rien configurer."""
    global DERNIER_MESSAGE, NAVIRE_INJOIGNABLE
    DERNIER_MESSAGE = ""
    NAVIRE_INJOIGNABLE = ""
    cfg = _read_config()
    choisi = cfg.get("ship_folder")
    if choisi:
        # un chemin relatif s'entend depuis le dossier de l'application (c'est
        # ainsi que la livraison désigne navires/<NOM>, quel que soit le
        # disque où elle est posée)
        if not os.path.isabs(choisi):
            # normpath : la configuration écrit « navires/<NOM> » ; sous
            # Windows, joindre sans normaliser donnait « …\navires/<NOM> »,
            # un chemin qui ne se comparait plus à lui-même (D-77)
            for base in (DATA_DIR, APP_DIR):
                if os.path.isdir(os.path.join(base, choisi)):
                    return os.path.normpath(os.path.join(base, choisi))
            choisi = os.path.normpath(os.path.join(APP_DIR, choisi))
        if os.path.isdir(choisi):
            return choisi
        if not _racine_joignable(choisi):
            # LE NAS NE RÉPOND PAS (D-77). Jusqu'à la 2.20, Carène ouvrait
            # alors, sans un mot, la copie `navires/<NOM>` posée à côté de
            # l'application — celle de l'exemple — et l'ENREGISTRAIT comme
            # navire du poste : aux lancements suivants, l'officier
            # travaillait sur le mauvais journal sans le savoir. Désormais on
            # ne remplace rien et on n'écrit rien : on dit que le dossier est
            # injoignable, et la fenêtre propose de réessayer.
            NAVIRE_INJOIGNABLE = choisi
            DERNIER_MESSAGE = (
                f"Le dossier du navire ne répond pas : {choisi}.\n"
                "Le disque ou le partage réseau qui le porte est injoignable "
                "(NAS pas encore monté, réseau coupé). Rien n'a été ouvert à "
                "sa place : rétablissez l'accès, puis « Réessayer ».")
            return choisi
        retrouve = _meme_navire_a_cote(choisi)
        if retrouve:
            # Un chemin absolu d'un autre poste (« /home/…/navires/<NOM> »
            # écrit par un essai à terre, puis une configuration restée en
            # place sous la livraison suivante) : le même navire est là, à
            # côté de l'application. On le rouvre sans un mot et on corrige
            # la configuration en relatif, pour ne plus poser la question au
            # bord à chaque lancement.
            set_ship_folder(retrouve)
            return retrouve
        supprime = cfg.get("navire_supprime") or ""
        if supprime and os.path.abspath(supprime) == os.path.abspath(choisi):
            # c'est l'application qui l'a mis de côté (« Supprimer le
            # navire… ») : l'écran « aucun navire » est bien ce qu'on veut,
            # pour en créer un autre à cet emplacement
            return choisi
        # le dossier choisi a disparu : on le dit et on retombe sur le navire
        # livré plutôt que d'afficher « Aucun navire » sans explication
        DERNIER_MESSAGE = (f"Le dossier du navire configuré n'existe plus : {choisi}. "
                           "Le navire livré avec l'application est ouvert à la place "
                           "(« Navire → Ouvrir un autre dossier de navire… » pour en choisir un autre).")
    livre = _navire_livre()
    if os.path.exists(os.path.join(DEFAULT_FOLDER, MANIFEST)) \
            or os.path.exists(os.path.join(DEFAULT_FOLDER, GEOMETRY)):
        # un `navire/` d'une version précédente, sans géométrie, à côté du
        # même navire livré complet : c'est le livré qu'on veut voir
        if livre and dossier_incomplet_face_a(DEFAULT_FOLDER, livre):
            return livre
        return DEFAULT_FOLDER
    return livre or DEFAULT_FOLDER


def _meme_navire_a_cote(chemin_disparu):
    """Le dossier `navires/<NOM>` d'à côté, si le chemin disparu se terminait
    ainsi et que ce dossier-là existe. Sinon None."""
    parts = [p for p in chemin_disparu.replace("\\", "/").split("/") if p]
    if len(parts) < 2 or parts[-2] != "navires":
        return None
    for base in (DATA_DIR, APP_DIR):
        cand = os.path.join(base, "navires", parts[-1])
        if os.path.exists(os.path.join(cand, MANIFEST)):
            return cand
    return None


def dossier_incomplet_face_a(dossier, livre):
    """`dossier` est-il le même navire que `livre`, mais sans sa géométrie ?"""
    if not livre or os.path.abspath(dossier) == os.path.abspath(livre):
        return False
    if os.path.exists(os.path.join(dossier, GEOMETRY)) or not os.path.exists(os.path.join(livre, GEOMETRY)):
        return False
    return (ship_name(dossier) or "").strip().upper() == (ship_name(livre) or "").strip().upper()


def navire_livre():
    return _navire_livre()


def set_ship_folder(path: str):
    """Retient le dossier du navire. Un dossier SOUS l'application est retenu
    en RELATIF : la livraison se pose sur n'importe quel disque (clé USB,
    « C:\\ », un autre poste) et doit y retrouver son navire. Un chemin absolu
    écrit ici par un essai sur une autre machine faisait dire à bord « le
    dossier configuré n'existe plus : /home/…/<NOM> »."""
    cfg = _read_config()
    absolu = os.path.abspath(path)
    retenu = absolu
    for base in (DATA_DIR, APP_DIR):
        try:
            rel = os.path.relpath(absolu, base)
        except ValueError:            # autre lecteur Windows : pas de relatif
            continue
        if not rel.startswith(".."):
            retenu = rel.replace(os.sep, "/")
            break
    cfg["ship_folder"] = retenu
    cfg.pop("navire_supprime", None)
    _write_config(cfg)
    return ship_folder()


def demander_point_au_lancement() -> bool:
    """Faut-il demander sur quel point travailler au lancement ?"""
    return bool(_read_config().get("demander_point", True))


def set_demander_point(valeur: bool):
    cfg = _read_config()
    cfg["demander_point"] = bool(valeur)
    _write_config(cfg)


def depot_github() -> str:
    """Le dépôt GitHub des mises à jour (D-70) : celui de la configuration du
    poste s'il y en a un, sinon la constante du logiciel."""
    from . import DEPOT_GITHUB
    d = str(_read_config().get("depot_github") or "").strip()
    return d or DEPOT_GITHUB


def serveur_maj() -> str:
    """L'adresse du serveur des mises à jour (D-85) : celle du poste, sinon
    celle du logiciel."""
    from . import SERVEUR_MAJ
    s = str(_read_config().get("serveur_maj") or "").strip()
    return s or SERVEUR_MAJ


def set_serveur_maj(adresse: str):
    cfg = _read_config()
    adresse = str(adresse or "").strip().rstrip("/")
    from . import SERVEUR_MAJ
    if adresse and adresse != SERVEUR_MAJ:
        cfg["serveur_maj"] = adresse
    else:
        cfg.pop("serveur_maj", None)
    _write_config(cfg)


def source_maj() -> str:
    """D'où viennent les mises à jour : le serveur donné par le poste, puis un
    dépôt GitHub donné par le poste (D-70, gardé pour qui en aurait un),
    puis le serveur du logiciel."""
    cfg = _read_config()
    s = str(cfg.get("serveur_maj") or "").strip()
    if s:
        return s
    d = str(cfg.get("depot_github") or "").strip()
    return d or serveur_maj()


def verifier_maj_au_lancement() -> bool:
    """Vérifier les mises à jour au lancement ? OUI par défaut (D-70) : le
    bord l'a voulu ainsi — sans réseau, une ligne dit que la vérification n'a
    pas pu avoir lieu, et c'est tout."""
    return bool(_read_config().get("verifier_maj_au_lancement", True))


def set_verifier_maj_au_lancement(valeur: bool):
    cfg = _read_config()
    cfg["verifier_maj_au_lancement"] = bool(valeur)
    _write_config(cfg)


def infobulles_actives() -> bool:
    """Les infobulles d'aide (boutons, champs, actions) sont-elles montrées ?

    ÉTEINTES par défaut : le bord les a trouvées envahissantes (« des
    infobulles dégueulasses quand je survole certains boutons »). Ce qu'on
    perd, c'est l'aide de survol ; ce qu'on garde, c'est ce qui est sous la
    souris SUR LE PLAN (colis, épontille), qui n'est pas de l'aide mais de
    l'information de chargement."""
    return bool(_read_config().get("infobulles", False))


def set_infobulles(valeur: bool):
    cfg = _read_config()
    cfg["infobulles"] = bool(valeur)
    _write_config(cfg)


# Les réglages du RÉPARTITEUR retenus d'un lancement à l'autre. Ce sont des
# réglages de TRAVAIL — comme « demander le point au lancement » ou les
# infobulles : ils disent comment le bord aime faire répartir, pas ce que
# porte le navire ni ce qu'il charge. Ils vont donc dans `carene.config.json`,
# à côté de l'application, et JAMAIS dans le dossier du navire : un dossier de
# navire décrit un navire, il n'a pas à changer parce qu'un officier a décoché
# une case. On ne retient que les cases de la fenêtre ; le jeu d'arrimage
# vient de la molette de la vue Chargement et ne se range pas ici (D-39).
CLES_REGLAGES_SOLVEUR = (
    "objectif", "viser_assiette", "assiette_cible_m", "equilibrer_tcg",
    "tcg_cible_m", "empiler", "rotation_permise", "disposition",
    "melanger_lots", "respecter_cale_imposee", "respecter_escales",
    "priorite_verticale", "vider",
)

# `disposition` s'est appelé `orientation` tant que le réglage imposait le
# grand côté des colis. Le poste du bord a une configuration écrite avec
# l'ancien nom : on la relit sous le nouveau plutôt que de la laisser tomber
# en silence et de rendre au bord des valeurs d'usine qu'il n'a pas demandées.
ANCIENNES_CLES_SOLVEUR = {"orientation": "disposition"}


def reglages_solveur() -> dict:
    """Ce que le bord avait réglé au dernier passage du répartiteur.

    Un dictionnaire, volontairement : la fenêtre y pioche ce qu'elle
    reconnaît, et un fichier écrit par une version d'avant (ou d'après) n'en
    fait pas tomber une. Vide = on prend les valeurs d'usine."""
    lu = _read_config().get("reglages_solveur")
    if not isinstance(lu, dict):
        return {}
    out = {k: v for k, v in lu.items() if k in CLES_REGLAGES_SOLVEUR}
    for ancienne, nouvelle in ANCIENNES_CLES_SOLVEUR.items():
        if nouvelle not in out and ancienne in lu:
            out[nouvelle] = lu[ancienne]
    return out


def set_reglages_solveur(valeurs: dict):
    """Retient les réglages du répartiteur. Le bord ne doit pas les recocher à
    chaque escale."""
    cfg = _read_config()
    cfg["reglages_solveur"] = {k: v for k, v in dict(valeurs or {}).items()
                               if k in CLES_REGLAGES_SOLVEUR}
    _write_config(cfg)


def has_tables(folder: str | None = None) -> bool:
    """Le navire a-t-il ses tables (donc peut-il calculer) ?"""
    folder = folder or ship_folder()
    return os.path.exists(os.path.join(folder, MANIFEST))


def has_geometry(folder: str | None = None) -> bool:
    folder = folder or ship_folder()
    return os.path.exists(os.path.join(folder, GEOMETRY))


def ship_exists(folder: str | None = None) -> bool:
    return has_tables(folder) or has_geometry(folder)


def ship_name(folder: str | None = None) -> str:
    """Nom du navire lu dans son manifeste, ou "" s'il n'y en a pas."""
    folder = folder or ship_folder()
    try:
        with open(os.path.join(folder, MANIFEST), encoding="utf-8") as f:
            return json.load(f).get("identification", {}).get("nom", "")
    except (OSError, ValueError):
        pass
    try:
        with open(os.path.join(folder, GEOMETRY), encoding="utf-8") as f:
            return json.load(f).get("ship_name", "")
    except (OSError, ValueError):
        return ""


def delete_ship(folder: str | None = None, keep_backup=True):
    """Supprime le navire en place. Renvoie le chemin de la sauvegarde.

    Le dossier n'est jamais effacé sans filet : il est renommé en
    `<nom>.supprime-<horodatage>` à côté, à charge de l'utilisateur de le jeter
    définitivement. Supprimer un navire est irréversible côté application, pas
    côté disque.
    """
    folder = folder or ship_folder()
    if not os.path.isdir(folder):
        return ""
    if not keep_backup:
        shutil.rmtree(folder)
        backup = ""
    else:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = f"{folder.rstrip(os.sep)}.supprime-{stamp}"
        os.rename(folder, backup)
    # on note que c'est nous qui l'avons retiré : `ship_folder()` ne doit pas
    # retomber sur le navire livré, l'utilisateur veut en créer un autre ici
    cfg = _read_config()
    cfg["ship_folder"] = os.path.abspath(folder)
    cfg["navire_supprime"] = os.path.abspath(folder)
    _write_config(cfg)
    return backup


PLANS_DIR = "plans"


def ranger_dans_plans(chemin: str, ship_folder: str) -> str:
    """Copie un fichier de plan dans `<navire>/plans/` et rend le chemin de la
    copie — ou le chemin d'origine si la copie est impossible.

    **Un navire est un dossier qu'on emporte tel quel.** Une image laissée là
    où l'utilisateur l'a prise met un chemin absolu dans `geometrie.json` : la
    vue est vide dès que le dossier change de machine, ou même de lettre de
    lecteur. Le PDF et le DXF sont déjà rangés ainsi (`pdf_plan.import_into`,
    `dxf_plan.import_into`) ; l'image l'est maintenant aussi.

    Un fichier déjà DANS le dossier du navire n'est pas recopié. Un homonyme
    déjà présent et de taille différente prend un suffixe : on n'écrase jamais
    le fond de plan d'une autre vue."""
    import shutil
    src = os.path.abspath(chemin)
    if not ship_folder or not os.path.exists(src):
        return src
    ship = os.path.abspath(ship_folder)
    try:
        dedans = os.path.commonpath([src, ship]) == ship
    except ValueError:            # autre lecteur (Windows)
        dedans = False
    if dedans:
        return src
    base, ext = os.path.splitext(os.path.basename(src))
    try:
        plans = os.path.join(ship, PLANS_DIR)
        os.makedirs(plans, exist_ok=True)
        dest = os.path.join(plans, base + ext)
        n = 1
        while os.path.exists(dest) \
                and os.path.getsize(dest) != os.path.getsize(src):
            dest = os.path.join(plans, f"{base}_{n}{ext}")
            n += 1
        if not os.path.exists(dest):
            shutil.copy2(src, dest)
    except OSError:
        # emplacement non inscriptible : mieux vaut le chemin d'origine, qui
        # marche au moins sur cette machine, que pas d'image du tout
        return src
    return dest


# pourquoi la dernière `perpendiculaires()` n'a rien rendu : même usage que
# DERNIER_MESSAGE_COUPLES — l'interface le relit après l'appel pour dire au
# bord ce qui manque, plutôt que de griser trois boutons sans un mot.
DERNIER_MESSAGE_PERPENDICULAIRES = ""


def perpendiculaires(folder):
    """(X de la PPAR, X de la PPAV) en mètres dans le repère du navire, ou None.

    Ce sont LES deux repères longitudinaux d'un plan de chantier : le profil
    et les plans de ponts sont cotés depuis elles, et le bord les cite en
    premier quand il dit comment il cale (« perpendiculaire arrière,
    perpendiculaire avant »). On les lit donc ici pour les proposer d'un
    bouton au calage, au lieu de faire retaper une abscisse lue au cartouche.

    `navire.json` les porte sous DEUX formes, toutes deux lues :

    - `dimensions.perpendiculaires.arriere_m` / `.avant_m` — la forme que lit
      le moteur (tirant d'eau local, angle d'envahissement) ;
    - `dimensions.x_perpendiculaire_ar_m` / `x_perpendiculaire_av_m` — les
      deux champs à plat du formulaire « Création du navire », tels que le
      brouillon les écrit avant d'être replié.

    None dès qu'il en manque une : une seule perpendiculaire ne cale rien, et
    proposer un bouton à moitié renseigné vaut moins que ne rien proposer.
    """
    global DERNIER_MESSAGE_PERPENDICULAIRES
    DERNIER_MESSAGE_PERPENDICULAIRES = ""
    if not folder:
        return None
    path = os.path.join(folder, MANIFEST)
    try:
        with open(path, encoding="utf-8") as f:
            dims = (json.load(f) or {}).get("dimensions") or {}
    except (OSError, ValueError) as e:
        if os.path.exists(path):
            DERNIER_MESSAGE_PERPENDICULAIRES = (
                f"{MANIFEST} est illisible ({type(e).__name__} : {e}) : le "
                "calage ne proposera pas les perpendiculaires.")
        return None
    niche = dims.get("perpendiculaires") or {}
    ar = niche.get("arriere_m", dims.get("x_perpendiculaire_ar_m"))
    av = niche.get("avant_m", dims.get("x_perpendiculaire_av_m"))
    try:
        ar, av = float(ar), float(av)
    except (TypeError, ValueError):
        DERNIER_MESSAGE_PERPENDICULAIRES = (
            "Les X des perpendiculaires ne sont pas renseignés dans "
            f"{MANIFEST} : le calage ne les proposera pas.")
        return None
    if ar != ar or av != av:          # NaN : autant dire qu'il n'y a rien
        return None
    return (ar, av)


COUPLES_FILE = "couples.csv"

# pourquoi la dernière `table_couples()` n'a rien rendu alors que le fichier
# était là : sans cela le champ « Sur le couple » du calage disparaît sans un
# mot, et l'on cale à la main un plan qui aurait pu se caler sur ses couples.
# Même usage que DERNIER_MESSAGE : l'interface le relit après l'appel.
DERNIER_MESSAGE_COUPLES = ""


def table_couples(folder):
    """La table des couples du dossier (`couples.csv` : n, x_m depuis C.0), ou
    une liste vide si le navire ne l'a pas — on n'invente pas de couples.

    Un fichier présent mais illisible retombe aussi sur la liste vide (mieux
    vaut caler à la main que sur des couples faux), mais il laisse alors son
    motif dans `DERNIER_MESSAGE_COUPLES`."""
    global DERNIER_MESSAGE_COUPLES
    DERNIER_MESSAGE_COUPLES = ""
    import csv
    path = os.path.join(folder, COUPLES_FILE)
    if not os.path.exists(path):
        return []
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out[int(r["n"])] = float(r["x_m"])
    except (OSError, ValueError, KeyError) as e:
        DERNIER_MESSAGE_COUPLES = (
            f"{COUPLES_FILE} est illisible ({type(e).__name__} : {e}) : le "
            "calage ne proposera pas « Sur le couple », il faudra saisir les "
            "abscisses à la main. Colonnes attendues : n, x_m.")
        return []
    if not out:
        DERNIER_MESSAGE_COUPLES = (
            f"{COUPLES_FILE} ne contient aucune ligne de couple : le calage "
            "ne proposera pas « Sur le couple ».")
        return []
    return [out.get(n, float("nan")) for n in range(max(out) + 1)]


# ------------------------------------------------------- une seule instance
# DEUX CARÈNE OUVERTS SUR LE MÊME POSTE ÉCRIVENT DANS LE MÊME JOURNAL. Le
# second n'en sait rien : il a lu les points au lancement, il enregistre
# par-dessus ce que le premier vient d'écrire, et le travail d'une escale
# disparaît sans un mot. Un logiciel de bord ne peut pas se permettre ça.
#
# Deux pièces, et elles ne font pas la même chose :
#
# - le VERROU (`QLockFile`) dit « il y en a déjà un ». Il porte le PID de
#   celui qui le tient, donc un verrou laissé par un plantage ou une coupure
#   de courant ne condamne pas le poste : `removeStaleLockFile` l'efface dès
#   lors que le processus n'existe plus ;
# - le GUICHET (`QLocalServer`) permet au second de RAMENER LE PREMIER AU
#   PREMIER PLAN. Sans lui, double-cliquer sur l'icône d'un Carène déjà
#   ouvert mais réduit ne ferait rien du tout — ce qui donne exactement envie
#   de le lancer une troisième fois.
#
# Le guichet est nommé d'après le dossier des données, haché : deux
# installations côte à côte (une clé USB et le disque) sont deux Carène
# différents, avec deux journaux différents, et ils ont le droit de tourner
# ensemble.
VERROU_FICHIER = "carene.verrou"


def chemin_verrou(dossier: str | None = None) -> str:
    """Le fichier verrou : `carene.verrou` à côté de la configuration."""
    return os.path.join(dossier or DATA_DIR, VERROU_FICHIER)


def nom_du_guichet(dossier: str | None = None) -> str:
    """Le nom du guichet local, dérivé du dossier des données.

    Haché, parce qu'un chemin complet ne fait pas un nom de socket valable
    (longueur, séparateurs, accents) ; en minuscules normalisées, parce que
    `C:\\Carene` et `c:\\carene` sont le même dossier sous Windows."""
    import hashlib
    base = os.path.normcase(os.path.abspath(dossier or DATA_DIR))
    return "carene-" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


class Verrou:
    """Le verrou d'instance : un seul Carène par installation.

    `obtenu` dit si c'est NOUS qui le tenons — donc si l'on peut ouvrir la
    fenêtre. `detenteur` décrit l'autre quand il est pris, pour le journal
    technique. Le verrou se libère à la fermeture du processus (`atexit`) et
    sur `liberer()` ; il ne doit jamais empêcher Carène de démarrer quand
    quelque chose d'inattendu arrive — dans le doute, on laisse passer.
    """

    def __init__(self, dossier: str | None = None):
        self.dossier = dossier or DATA_DIR
        self.chemin = chemin_verrou(self.dossier)
        self.lock = None
        self.serveur = None
        self.obtenu = False
        self.detenteur = ""

    # --------------------------------------------------------------- prise
    def prendre(self) -> bool:
        from PySide6.QtCore import QLockFile
        try:
            os.makedirs(self.dossier, exist_ok=True)
        except OSError:
            pass
        self.lock = QLockFile(self.chemin)
        # jamais périmé PAR LE TEMPS : un chargement d'escale dure des heures,
        # et un Carène ouvert depuis le matin n'est pas un verrou mort. C'est
        # le PID qui tranche, pas le chronomètre.
        self.lock.setStaleLockTime(0)
        self.obtenu = bool(self.lock.tryLock(0))
        if not self.obtenu:
            self.detenteur = self._decrire()
            # le détenteur n'existe plus (plantage, coupure) : on reprend
            if self.lock.removeStaleLockFile():
                self.obtenu = bool(self.lock.tryLock(0))
                if self.obtenu:
                    self.detenteur = ""
        if self.obtenu:
            import atexit
            atexit.register(self.liberer)
        return self.obtenu

    def _decrire(self) -> str:
        """Qui tient le verrou, en une ligne — pour le journal technique.

        `getLockInfo` rend (pid, machine, application) selon les liaisons
        Python, parfois précédé du booléen de réussite : on accepte les deux
        formes plutôt que de laisser un détail de liaison empêcher un
        démarrage."""
        try:
            infos = self.lock.getLockInfo()
        except (AttributeError, TypeError, RuntimeError):
            return ""
        if not infos:
            return ""
        infos = list(infos)
        if isinstance(infos[0], bool):
            if not infos[0]:
                return ""
            infos = infos[1:]
        if len(infos) < 3:
            return ""
        pid, machine, appli = infos[0], infos[1], infos[2]
        return f"PID {pid}, {appli or 'application inconnue'} sur {machine or 'ce poste'}"

    def liberer(self):
        """Rend le verrou et ferme le guichet. Appelable deux fois."""
        if self.serveur is not None:
            try:
                self.serveur.close()
            except RuntimeError:      # détruit côté C++ avec l'application
                pass
            self.serveur = None
        if self.lock is not None and self.obtenu:
            try:
                self.lock.unlock()
            except RuntimeError:
                pass
        self.obtenu = False

    # -------------------------------------------------------------- guichet
    def ecouter(self, fenetre) -> bool:
        """Ouvre le guichet qui permet à un second Carène de nous réveiller.

        Rend Faux si le guichet n'a pas pu s'ouvrir (pas de QtNetwork, droits) :
        ce n'est pas une raison de refuser de démarrer — le verrou, lui, joue
        toujours son rôle. On perd seulement la remontée au premier plan."""
        if not self.obtenu:
            return False
        try:
            from PySide6.QtNetwork import QLocalServer
        except ImportError:
            return False
        nom = nom_du_guichet(self.dossier)
        # un guichet laissé par un processus mort empêcherait le nôtre de
        # s'ouvrir : personne n'écoute derrière, on peut l'enlever
        QLocalServer.removeServer(nom)
        srv = QLocalServer()
        try:
            srv.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        except AttributeError:        # pragma: no cover - vieilles liaisons
            pass
        if not srv.listen(nom):
            return False
        srv.newConnection.connect(lambda: self._on_appel(srv, fenetre))
        self.serveur = srv
        return True

    @staticmethod
    def _on_appel(srv, fenetre):
        """Un second Carène s'annonce : on se montre."""
        sock = srv.nextPendingConnection()
        if sock is not None:
            sock.disconnectFromServer()
        try:
            fenetre.showNormal()
            fenetre.raise_()
            fenetre.activateWindow()
        except RuntimeError:          # fenêtre détruite : rien à lever
            pass


def verrou_instance(dossier: str | None = None) -> Verrou:
    """Prend le verrou d'instance de cette installation.

    Rend le `Verrou` : `obtenu` faux veut dire qu'un Carène est déjà ouvert
    sur ce poste. L'appelant garde l'objet vivant tant que l'application
    tourne — un verrou ramassé par le ramasse-miettes ne verrouille plus rien."""
    v = Verrou(dossier)
    v.prendre()
    return v


def reveiller_linstance_ouverte(dossier: str | None = None, attente_ms: int = 900) -> bool:
    """Demande au Carène déjà ouvert de se montrer. Vrai s'il a répondu.

    Faux ne veut pas dire « il n'y en a pas » : il peut être en train de
    démarrer, ou son guichet n'a pas pu s'ouvrir. Le verrou reste le juge."""
    try:
        from PySide6.QtNetwork import QLocalSocket
    except ImportError:
        return False
    sock = QLocalSocket()
    sock.connectToServer(nom_du_guichet(dossier))
    if not sock.waitForConnected(attente_ms):
        return False
    sock.write(b"lever")
    sock.flush()
    sock.waitForBytesWritten(attente_ms)
    sock.disconnectFromServer()
    return True
