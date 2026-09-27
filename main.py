# -*- coding: utf-8 -*-
"""Point d'entrée : python main.py

`--chemins` affiche où l'application cherche le navire et écrit sa
configuration, puis s'arrête. C'est la première chose à demander quand
quelqu'un dit « il ne trouve pas mon navire » — surtout en exécutable gelé,
où le code vit dans un dossier temporaire et les données non.

`--sauvegarde [fichier.zip]` écrit la sauvegarde du navire (le même zip que
« Navire › Exporter une sauvegarde du navire… ») sans ouvrir la fenêtre :
c'est ce qu'une tâche planifiée du poste appelle chaque soir. Sans nom de
fichier, le zip va dans `sauvegardes/` à côté des données, nommé par le
navire et l'instant.

`--dependances` dit, paquet par paquet, ce qui est installé et ce qui
manque, puis s'arrête (code 1 s'il manque quelque chose). Le même contrôle
tourne à CHAQUE lancement, avant d'importer Qt : un poste où il manque un
paquet a droit à une phrase et à la commande à lancer, pas à un traceback.
"""
import sys


def dependances_ok():
    """Le contrôle du lancement. Vrai si tout est là ; sinon le message est
    affiché (boîte Windows + console) et on rend Faux."""
    from carene import dependances
    manques = dependances.verifier()
    if not manques and not dependances.python_trop_vieux():
        return True
    dependances.avertir(dependances.message(manques))
    return False


def chemins():
    from carene import app_paths
    gele = getattr(sys, "frozen", False)
    print(f"Carène — exécutable gelé : {'oui' if gele else 'non (sources)'}")
    print(f"  application  : {app_paths.APP_DIR}")
    print(f"  données      : {app_paths.DATA_DIR}")
    print(f"  configuration: {app_paths.CONFIG_FILE}")
    print(f"  navire       : {app_paths.ship_folder()}")
    print(f"  navire présent : {'oui' if app_paths.ship_exists() else 'non'}")
    for ex in app_paths.navires_exemple():
        print(f"  navire d'exemple livré : {ex}  (copié en navire au premier "
              "lancement d'une installation vierge, jamais ensuite)")
    nom = app_paths.ship_name()
    if nom:
        print(f"  nom du navire  : {nom}")


def sauvegarde(arguments):
    """`--sauvegarde [fichier.zip]` : écrit la sauvegarde, dit où, s'arrête.
    Code de retour 1 si rien n'a pu être écrit — une tâche planifiée doit
    pouvoir s'en apercevoir."""
    import os
    from carene import __version__, app_paths
    from carene.core import sauvegarde as S
    folder = app_paths.ship_folder()
    if not app_paths.ship_exists(folder):
        print("Aucun navire à sauvegarder (dossier : %s)." % folder)
        return 1
    nom = app_paths.ship_name(folder) or os.path.basename(folder)
    chemin = next((a for a in arguments if not a.startswith("--")), "")
    if not chemin:
        dossier = os.path.join(app_paths.DATA_DIR, "sauvegardes")
        os.makedirs(dossier, exist_ok=True)
        chemin = os.path.join(dossier, S.nom_de_fichier(nom))
    try:
        m = S.exporter(folder, chemin, config=app_paths.config_file(),
                       version_carene=__version__)
    except (S.SauvegardeInvalide, OSError) as e:
        print("Sauvegarde impossible : %s" % e)
        return 1
    print("Sauvegarde écrite : %s" % chemin)
    print(m.resume())
    return 0


if __name__ == "__main__":
    if "--dependances" in sys.argv[1:]:
        from carene import dependances
        print(dependances.rapport())
        manques = dependances.verifier()
        if manques or dependances.python_trop_vieux():
            print()
            print(dependances.message(manques))
            sys.exit(1)
        print("Tout est en place.")
        sys.exit(0)
    if not dependances_ok():
        sys.exit(3)
    if "--chemins" in sys.argv[1:]:
        chemins()
    elif "--sauvegarde" in sys.argv[1:]:
        args = sys.argv[1:]
        sys.exit(sauvegarde(args[args.index("--sauvegarde") + 1:]))
    else:
        from carene.mainwindow import main
        main()
