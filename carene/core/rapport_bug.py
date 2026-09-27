# -*- coding: utf-8 -*-
"""Signaler un problème : le rapport que le bord envoie, prêt à lire (D-63).

Le bord (22/09/2026) : « un truc pour faire remonter les bugs (qui arrivent
sur mon email). On devrait d'ailleurs inviter l'utilisateur à remonter les
bugs dès le message d'avertissement au lancement. »

Un rapport de bug utile tient en trois choses : **ce qu'on faisait**, **ce
qui s'est passé**, et **ce qui tournait**. Les deux premières, seul
l'utilisateur les connaît ; la troisième, le logiciel la connaît seul — et
c'est elle qu'on oublie toujours de joindre. Ce module l'assemble : version,
système, Python et Qt, navire et point ouverts, verdict affiché, et les
dernières lignes du journal technique (là où les erreurs atterrissent déjà).

Il ne fait qu'assembler du texte. L'envoi — un signalement sur GitHub,
presse-papiers ou fichier — appartient à la fenêtre.

**Depuis la 3.5.4 (D-91), les signalements passent par GitHub**, dans les
« Issues » du dépôt public de Carène, et plus par courriel. Le dépôt étant
public, le nom du navire et le chemin de son dossier sont MASQUÉS par défaut
(`texte(..., masquer_navire=True)`), partout dans le rapport, journal compris.
"""
from __future__ import annotations

import datetime as _dt
import os
import platform
import sys
import urllib.parse

# Là où les signalements arrivent : les « Issues » du dépôt public de Carène
# (D-91). En un seul endroit : la fenêtre, l'avertissement du lancement,
# « À propos » et l'aide la citent toutes.
SIGNALEMENTS = "https://github.com/theptitprince/Carene/issues"
CONTACT = SIGNALEMENTS          # l'ancien nom, gardé pour qui le lit encore
MASQUE = "<navire masqué>"

LIGNES_JOURNAL = 120          # ce qu'on joint du journal technique


def _sans_risque(appel, defaut=""):
    """Un renseignement qui manque ne doit pas empêcher d'envoyer le rapport."""
    try:
        v = appel()
    except Exception:                       # noqa: BLE001 - jamais bloquant
        return defaut
    return defaut if v is None else v


def contexte(win=None):
    """Ce qui tournait, en clair : [(libellé, valeur)].

    `win` est facultatif — on doit pouvoir faire un rapport même quand la
    fenêtre principale n'a pas pu s'ouvrir."""
    from .. import __version__
    lignes = [("Carène", __version__),
              ("Date", _dt.datetime.now().strftime("%d/%m/%Y %H:%M")),
              ("Système", f"{platform.system()} {platform.release()}"),
              ("Python", sys.version.split()[0]),
              ("Exécutable gelé", "oui" if getattr(sys, "frozen", False)
               else "non (sources)")]
    try:
        import PySide6
        from PySide6 import QtCore
        lignes.append(("PySide6 / Qt", f"{PySide6.__version__} / {QtCore.qVersion()}"))
    except Exception:                       # noqa: BLE001
        lignes.append(("PySide6 / Qt", "illisible"))
    try:
        from .. import app_paths
        dossier = app_paths.ship_folder()
        lignes.append(("Navire", _sans_risque(lambda: app_paths.ship_name(dossier))
                       or os.path.basename(dossier or "") or "aucun"))
        lignes.append(("Dossier du navire", dossier or "—"))
    except Exception:                       # noqa: BLE001
        pass
    if win is not None:
        point = getattr(win, "point", None)
        if point is not None:
            lignes.append(("Point du journal", _sans_risque(
                lambda: f"{point.titre} ({point.etat})", "—")))
        lignes.append(("Verdict affiché", _sans_risque(
            lambda: win.pill_verdict.text(), "—")))
        # la vue est une pile, pas des onglets : on la nomme par son rang
        noms = ("Journal", "Capacités", "Chargement", "Stabilité")
        lignes.append(("Vue ouverte", _sans_risque(
            lambda: noms[win.tabs.currentIndex()], "—")))
        lignes.append(("Lecture seule", "oui" if getattr(win, "lecture_seule", False)
                       else "non"))
    return lignes


def journal(n=LIGNES_JOURNAL):
    """Les dernières lignes du journal technique — c'est là que tombent les
    erreurs, et personne ne pense à aller les chercher."""
    try:
        from .. import journal_technique
        return journal_technique.dernieres_lignes(n)
    except Exception as e:                  # noqa: BLE001
        return f"(journal technique illisible : {e})"


MODELE = """Ce que je faisais :
{geste}

Ce qui s'est passé :
{probleme}

Ce que j'attendais :
{attendu}
"""


def _navire_et_dossier():
    """(nom du navire, dossier du navire) — ce qu'on masque."""
    try:
        from .. import app_paths
        dossier = app_paths.ship_folder() or ""
        nom = _sans_risque(lambda: app_paths.ship_name(dossier)) or ""
        return nom, dossier
    except Exception:                       # noqa: BLE001
        return "", ""


def masquer(corps):
    """Le rapport sans le nom du navire ni le chemin de son dossier (D-91)."""
    nom, dossier = _navire_et_dossier()
    candidats = [dossier, dossier.replace("\\", "/"), dossier.replace("/", "\\"),
                 os.path.basename(dossier), nom]
    for mot in sorted({c for c in candidats if c and len(c) >= 3}, key=len,
                      reverse=True):
        corps = corps.replace(mot, MASQUE)
    return corps


def texte(geste="", probleme="", attendu="", win=None, avec_journal=True,
          masquer_navire=False):
    """Le rapport complet, tel qu'il part : le récit de l'utilisateur d'abord
    — c'est ce qui se lit —, les renseignements techniques ensuite.
    `masquer_navire` : le nom et le dossier du navire remplacés partout."""
    blocs = [MODELE.format(geste=geste.strip() or "(à compléter)",
                           probleme=probleme.strip() or "(à compléter)",
                           attendu=attendu.strip() or "(à compléter)")]
    blocs.append("-" * 60)
    blocs.append("CE QUI TOURNAIT")
    for lib, val in contexte(win):
        blocs.append(f"  {lib:<20} {val}")
    if avec_journal:
        blocs.append("")
        blocs.append("-" * 60)
        blocs.append(f"JOURNAL TECHNIQUE — {LIGNES_JOURNAL} dernières lignes")
        blocs.append(journal())
    corps = "\n".join(blocs)
    return masquer(corps) if masquer_navire else corps


def sujet(win=None):
    """Le titre du signalement : la version, jamais le navire — le dépôt est
    public (D-91)."""
    from .. import __version__
    return f"Carène {__version__} — signalement"


# Une URL a une limite pratique (au-delà de quelques milliers de caractères,
# navigateurs et serveurs coupent) : au-delà, le corps est tronqué et la
# fenêtre a mis le rapport COMPLET dans le presse-papiers, à coller.
URL_MAX = 1800


def url_signalement(corps, win=None, depot=SIGNALEMENTS):
    """L'URL d'un nouveau signalement sur GitHub, titre et corps remplis, et
    si le corps a dû être tronqué. Rend (url, tronque)."""
    tronque = len(corps) > URL_MAX
    if tronque:
        corps = (corps[:URL_MAX].rstrip()
                 + "\n\n[…] Rapport tronqué : le rapport complet est dans le "
                   "presse-papiers — collez-le ici à la place de ce texte.")
    q = urllib.parse.urlencode({"title": sujet(win), "body": corps},
                               quote_via=urllib.parse.quote)
    return f"{depot.rstrip('/')}/new?{q}", tronque


def nom_de_fichier():
    from .. import __version__
    return "carene_%s_signalement_%s.txt" % (
        __version__, _dt.datetime.now().strftime("%Y-%m-%d_%H%M"))


def ecrire(dossier, corps):
    """Écrit le rapport dans un fichier et rend son chemin."""
    os.makedirs(dossier or ".", exist_ok=True)
    chemin = os.path.join(dossier, nom_de_fichier())
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(corps)
    return chemin
