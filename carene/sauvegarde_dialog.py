# -*- coding: utf-8 -*-
"""Les deux gestes de sauvegarde, depuis la fenêtre principale.

*Navire › Exporter une sauvegarde du navire…* écrit le zip ; *Navire ›
Importer une sauvegarde…* le relit. Toute la logique est dans
`core.sauvegarde` (sans Qt) ; ici il n'y a que les questions à poser et les
messages à afficher — et la règle de la maison : on dit ce qui va se passer
AVANT de le faire, on dit ce qui s'est passé APRÈS, et rien n'est effacé.
"""
import os

from PySide6.QtWidgets import QCheckBox, QFileDialog, QMessageBox

from . import __version__, app_paths
from .core import sauvegarde as S

DOSSIER_SAUVEGARDES = "sauvegardes"      # à côté de l'application, par défaut


def dossier_des_sauvegardes():
    """Où les sauvegardes se rangent par défaut : `sauvegardes/` à côté des
    données de l'application. Un dossier que l'explorateur montre, pas un
    recoin du profil utilisateur — on doit pouvoir le copier sur une clé."""
    d = os.path.join(app_paths.DATA_DIR, DOSSIER_SAUVEGARDES)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return app_paths.DATA_DIR
    return d


def dossier_des_navires():
    """Où les navires vivent sur ce poste : le `navires/` qui contient le
    navire ouvert, sinon `navires/` à côté des données."""
    courant = os.path.normpath(app_paths.ship_folder())
    parent = os.path.dirname(courant)
    if os.path.basename(parent) == "navires" and os.path.isdir(parent):
        return parent
    return os.path.join(app_paths.DATA_DIR, "navires")


def exporter(win, chemin=None):
    """Écrit la sauvegarde du navire ouvert. Renvoie le chemin écrit, ou "".

    Un point modifié et non enregistré n'est PAS dans le dossier du navire,
    donc pas dans la sauvegarde : on le dit et on propose d'enregistrer
    d'abord — une sauvegarde faite « pour être tranquille » qui oublie la
    dernière heure de travail est pire qu'aucune."""
    folder = app_paths.ship_folder()
    if not app_paths.ship_exists(folder):
        QMessageBox.information(win, "Exporter une sauvegarde",
                                "Aucun navire à sauvegarder.")
        return ""
    if win._dirty and win._confirmations_actives():
        rep = QMessageBox.question(
            win, "Exporter une sauvegarde",
            f"{win.point.titre} a des modifications non enregistrées : elles ne "
            "seraient pas dans la sauvegarde.\n\nL'enregistrer d'abord ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Yes)
        if rep == QMessageBox.StandardButton.Cancel:
            return ""
        if rep == QMessageBox.StandardButton.Yes and not win.save_point():
            return ""
    nom = app_paths.ship_name(folder) or os.path.basename(folder)
    if not chemin:
        propose = os.path.join(dossier_des_sauvegardes(), S.nom_de_fichier(nom))
        chemin, _f = QFileDialog.getSaveFileName(
            win, "Exporter une sauvegarde du navire", propose,
            "Sauvegarde Carène (*.zip)")
        if not chemin:
            return ""
        if not chemin.lower().endswith(".zip"):
            chemin += ".zip"
    try:
        m = S.exporter(folder, chemin, config=app_paths.config_file(),
                       version_carene=__version__)
    except (S.SauvegardeInvalide, OSError) as e:
        QMessageBox.critical(win, "Exporter une sauvegarde", f"Échec : {e}")
        return ""
    win.statusBar().showMessage(f"Sauvegarde écrite : {chemin}", 15000)
    if win._confirmations_actives():
        QMessageBox.information(
            win, "Sauvegarde écrite",
            f"{chemin}\n\n{m.resume()}\n\nCe zip se copie sur une clé, s'envoie "
            "par mail, et se relit par « Navire › Importer une sauvegarde… » "
            "dans cette version de Carène comme dans les suivantes.")
    return chemin


def importer(win, chemin=None, reprendre_config=None):
    """Relit une sauvegarde et en fait le navire de l'installation.

    Renvoie le `Resultat` de `core.sauvegarde.importer`, ou None. Le navire
    en place est mis de côté, jamais écrasé, et on le dit avant."""
    if not win._confirmer_abandon():
        return None
    if not chemin:
        chemin, _f = QFileDialog.getOpenFileName(
            win, "Importer une sauvegarde", dossier_des_sauvegardes(),
            "Sauvegarde Carène (*.zip)")
        if not chemin:
            return None
    try:
        m = S.lire(chemin)
    except S.SauvegardeInvalide as e:
        QMessageBox.critical(win, "Importer une sauvegarde", str(e))
        return None
    navires = dossier_des_navires()
    dest = os.path.join(navires, m.dossier or m.navire or "navire")
    en_place = os.path.isdir(dest)
    if reprendre_config is None:
        reprendre_config = False
    if win._confirmations_actives():
        boite = QMessageBox(win)
        boite.setIcon(QMessageBox.Icon.Question)
        boite.setWindowTitle("Importer une sauvegarde")
        texte = m.resume() + "\n\n"
        if en_place:
            texte += (f"Le navire déjà en place ({dest}) sera mis de côté sous "
                      f"{os.path.basename(dest)}.avant_import-<date> — rien n'est "
                      "effacé, vous pourrez y revenir ou le jeter vous-même.\n\n")
        else:
            texte += f"Le navire sera écrit dans {dest}.\n\n"
        texte += "Importer, puis ouvrir ce navire ?"
        boite.setText(texte)
        case = None
        if m.config:
            case = QCheckBox("Reprendre aussi les réglages de l'application "
                             "(répartiteur, préférences)")
            case.setChecked(bool(reprendre_config))
            boite.setCheckBox(case)
        ok = boite.addButton("Importer", QMessageBox.ButtonRole.AcceptRole)
        boite.addButton("Annuler", QMessageBox.ButtonRole.RejectRole)
        boite.setDefaultButton(ok)
        boite.exec()
        if boite.clickedButton() is not ok:
            return None
        if case is not None:
            reprendre_config = case.isChecked()
    try:
        r = S.importer(chemin, navires, config_cible=app_paths.config_file(),
                       reprendre_config=bool(reprendre_config))
    except (S.SauvegardeInvalide, OSError) as e:
        QMessageBox.critical(win, "Importer une sauvegarde",
                             f"{e}\n\nLe navire en place n'a pas été touché.")
        return None
    from .condition_model import LoadingCondition
    app_paths.set_ship_folder(r.dossier)
    win.condition = LoadingCondition()
    win._dirty = False
    win.open_ship()
    message = f"Sauvegarde importée : {r.fichiers} fichiers dans {r.dossier}."
    if r.mis_de_cote:
        message += f" L'ancien navire est conservé sous {r.mis_de_cote}."
    if r.config_reprise:
        message += " Réglages de l'application repris."
    win.statusBar().showMessage(message, 20000)
    if win._confirmations_actives():
        QMessageBox.information(win, "Sauvegarde importée", message)
    return r
