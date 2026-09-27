# -*- coding: utf-8 -*-
"""carene.core — moteur de calcul de chargement & stabilité.

Ce paquet ne contient AUCUNE donnée propre à un navire : ni table hydrostatique,
ni pantocarène, ni capacité, ni critère chiffré au-delà des seuils réglementaires
universels (IMO IS Code 2008, formules du critère météo). Toutes les données
"bateau" sont lues depuis un dossier "navire virtuel" (voir navires/<NOM>/ et
carene.core.navire.Navire.load) au format CSV/JSON, indépendant du moteur et
déplaçable d'un ordinateur à l'autre.

Aucune dépendance à PySide6 / Qt : ce paquet s'utilise en ligne de commande ou
depuis n'importe quel script Python, séparément de l'application graphique
Carène.
"""

__all__ = ["navire", "interp", "hydrostatics", "stability", "criteria", "weather", "condition"]
