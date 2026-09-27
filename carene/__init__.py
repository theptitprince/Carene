# -*- coding: utf-8 -*-
"""Carène — logiciel de chargement & stabilité.

ETDEL © 2026. Tous droits réservés.
"""

__version__ = "3.6.0"
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
__auteur__ = "Etienne DELON"
__copyright__ = "ETDEL © 2026"
# La ligne qu'on colle partout où le logiciel se présente : fenêtre « À
# propos », barre d'état au lancement, pied de page des rapports exportés.
MENTION = f"Carène {__version__} — {__copyright__}"
# Ce que le logiciel est, et n'est pas : rappelé au lancement, dans la vue
# Stabilité et en tête de chaque export.
AVERTISSEMENT = ("Carène est une aide au chargement et à la stabilité. Il n'est ni "
                 "certifié ni réglementaire : seul le dossier de stabilité approuvé "
                 "et l'appréciation du capitaine font foi.")
