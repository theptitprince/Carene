# -*- coding: utf-8 -*-
# Carène, par ETDEL — https://github.com/theptitprince/Carene
# Copyright © 2026 ETDEL — GPL-3.0-or-later, avec conditions additionnelles
# (article 7) : voir les fichiers LICENSE et NOTICE.
"""Carène — logiciel de chargement & stabilité.

Carène est un logiciel libre : vous pouvez le redistribuer et le modifier
selon les termes de la licence publique générale GNU (GPL), version 3 ou (à
votre choix) toute version ultérieure, telle que publiée par la Free Software
Foundation. Il est distribué SANS AUCUNE GARANTIE, ni de qualité marchande,
ni d'adéquation à un usage particulier. Voir le fichier LICENSE.

La licence porte des conditions additionnelles (article 7 b et c), dans le
fichier NOTICE : toute copie ou version modifiée garde, visible, la mention
ATTRIBUTION ci-dessous, et une version modifiée dit qu'elle l'est.
"""

__version__ = "3.6.2"
# LE DÉPÔT DES MISES À JOUR (D-70) : « propriétaire/dépôt » sur GitHub, celui
# dont les *Releases* portent les zips de livraison. C'est une donnée du
# LOGICIEL, pas du navire : elle vit ici, à côté de la version, et la clé
# `depot_github` de carene.config.json peut la surcharger sur un poste.
# VIDE depuis D-75 : Carène est un projet local, il n'y a aucun dépôt en
# ligne pour l'instant — la vérification le dit en une ligne, sans rien
# demander à personne. Le mécanisme reste écrit et testé pour le jour où.
DEPOT_GITHUB = ""
# Le serveur des mises à jour du bord (D-85) : `derniere.json` et le zip du
# programme seul. Adresse provisoire donnée le 24/09/2026 ; un poste peut en
# donner une autre (Aide › Serveur des mises à jour…).
SERVEUR_MAJ = "http://theptitprince.fr/carene"
__auteur__ = "ETDEL"
__copyright__ = "ETDEL © 2026"
# La licence (D-93) : GNU GPL v3 ou ultérieure — le texte est dans LICENSE
__licence__ = "GPL-3.0-or-later"
# La ligne qu'on colle partout où le logiciel se présente : fenêtre « À
# propos », barre d'état au lancement, pied de page des rapports exportés.
MENTION = f"Carène {__version__} — {__copyright__}"
# Le dépôt public du code source (D-94) — à ne pas confondre avec
# DEPOT_GITHUB, celui des mises à jour, qui reste vide.
DEPOT = "https://github.com/theptitprince/Carene"
# LA MENTION À CONSERVER (D-94). La GPL v3 permet à l'auteur d'ajouter des
# conditions (article 7) : celles de Carène sont dans le fichier NOTICE.
# Toute copie ou version modifiée garde cette ligne, intacte et visible, dans
# son « À propos » et dans sa documentation ; elle reste en français. Elle ne
# remplace pas MENTION, qui doit tenir dans le pied de page des PDF.
ATTRIBUTION = f"Carène, par ETDEL — {DEPOT}"
# Où lire les deux textes, pour qui n'a pas le dépôt sous la main (un
# exécutable les embarque aussi, à côté de ses bibliothèques).
LICENCE_EN_LIGNE = "https://www.gnu.org/licenses/gpl-3.0.html"
NOTICE_EN_LIGNE = f"{DEPOT}/blob/main/NOTICE"
# Ce que le logiciel est, et n'est pas : rappelé au lancement, dans la vue
# Stabilité et en tête de chaque export.
AVERTISSEMENT = ("Carène est une aide au chargement et à la stabilité. Il n'est ni "
                 "certifié ni réglementaire : seul le dossier de stabilité approuvé "
                 "et l'appréciation du capitaine font foi.")


def mentions_legales_html():
    """Les mentions légales des deux « À propos » (fenêtre principale et
    éditeur de plans), en texte riche pour QMessageBox : la mention à
    conserver avec le lien du dépôt, le copyright, la licence et ses
    conditions additionnelles, l'absence de garantie, et où lire la licence
    et les conditions. Sans Qt : se vérifie sans fenêtre."""
    lien = f"<a href='{DEPOT}'>{DEPOT}</a>"
    return (
        f"{ATTRIBUTION.replace(DEPOT, lien)}<br>"
        "<span style='color:#888'>Copyright © 2026 ETDEL<br>"
        "Logiciel libre : GNU GPL version 3 ou ultérieure, avec conditions "
        "additionnelles (article 7 b et c, fichier NOTICE).<br>"
        "SANS AUCUNE GARANTIE.<br>"
        "Texte de la licence : fichier LICENSE, ou "
        f"<a href='{LICENCE_EN_LIGNE}'>{LICENCE_EN_LIGNE}</a><br>"
        "Conditions additionnelles : fichier NOTICE, ou "
        f"<a href='{NOTICE_EN_LIGNE}'>{NOTICE_EN_LIGNE}</a><br>"
        "Une version modifiée doit le dire et ne pas se présenter comme "
        "l'original.</span>")
