# -*- coding: utf-8 -*-
"""Le catalogue des plans PDF du navire : les plans du chantier, rangés une
fois, nommés, et d'où l'on affecte une page à une vue.

Avant, « Importer le plan… » rouvrait une boîte de fichiers à chaque fois, et
le même PDF d'ensemble était recherché sur le disque du bord dix fois de
suite. Le bord demande un **catalogue de plans PDF** : les plans entrent une
fois dans le dossier du navire, ils y portent un titre et une référence, et
l'on choisit ensuite « telle page de tel plan pour telle vue ».

Deux règles tiennent tout le module :

- **rien n'est stocké deux fois.** Le catalogue dit quels PDF le navire
  possède ; il ne dit PAS quelle vue s'en sert. Cela, on le DÉDUIT des
  `Calibrated.pdf_path` / `pdf_page` des vues (`utilisations`) — une vue
  re-importée depuis un autre plan n'a donc jamais à être « désinscrite »
  d'un catalogue qui la croirait encore là ;
- **un navire est un dossier qu'on emporte.** Les chemins du catalogue sont
  des noms de fichier relatifs au dossier `plans/` du navire, jamais des
  chemins absolus : le dossier change de machine, de disque ou de lettre de
  lecteur sans que rien ne se perde.

Ce module ne dépend pas de Qt : il se teste seul (`test_catalogue_plans.py`),
et la fenêtre ne fait qu'y piocher.
"""
from __future__ import annotations
from .ecriture import ecriture_atomique

import json
import os
import re

FICHIER = "catalogue.json"
PLANS_DIR = "plans"

# Les plans du chantier sont numérotés d'un préfixe (une lettre et trois
# chiffres, « C900 » dans les exemples ci-dessous) + six chiffres + un
# indice de révision : C900630006F. La référence telle qu'elle s'écrit et se
# dit à bord regroupe ces six chiffres en 4 + 2 — « C900-6300-06 », qui est
# aussi la forme citée par le manuel d'assujettissement.
MOTIF_CHANTIER = re.compile(r"^(C\d{3})[-_ ]?(\d{4})[-_ ]?(\d{2})([A-Z0-9]?)(.*)$",
                            re.IGNORECASE)


# ------------------------------------------------------------------ chemins
def dossier_plans(ship_folder: str) -> str:
    return os.path.join(ship_folder or "", PLANS_DIR)


def chemin_catalogue(ship_folder: str) -> str:
    return os.path.join(dossier_plans(ship_folder), FICHIER)


def chemin_du_plan(ship_folder: str, fichier: str) -> str:
    """Le chemin absolu d'une entrée du catalogue (`fichier` est relatif au
    dossier `plans/`)."""
    return os.path.join(dossier_plans(ship_folder),
                        str(fichier or "").replace("\\", "/"))


# ------------------------------------------------------------------ lecture
def catalogue_vide() -> dict:
    return {"plans": []}


def charger(ship_folder: str) -> dict:
    """Le catalogue du navire, toujours un dictionnaire `{"plans": [...]}`.

    Un fichier absent ou illisible rend un catalogue VIDE plutôt qu'une
    erreur : le catalogue est un confort, pas une condition pour travailler —
    l'import par la boîte de fichiers doit rester possible même si ce fichier
    a été abîmé."""
    try:
        with open(chemin_catalogue(ship_folder), encoding="utf-8") as f:
            lu = json.load(f)
    except (OSError, ValueError):
        return catalogue_vide()
    if not isinstance(lu, dict):
        return catalogue_vide()
    plans = lu.get("plans")
    if not isinstance(plans, list):
        plans = []
    propres = []
    for e in plans:
        if isinstance(e, dict) and str(e.get("fichier") or "").strip():
            propres.append(_normaliser(e))
    out = dict(lu)
    out["plans"] = propres
    return out


def _normaliser(entree: dict) -> dict:
    """Une entrée complète, quelles que soient les clés du fichier lu."""
    fichier = os.path.basename(str(entree.get("fichier") or "").replace("\\", "/"))
    pages = entree.get("pages")
    try:
        pages = int(pages)
    except (TypeError, ValueError):
        pages = 0
    out = dict(entree)
    out.update({
        "fichier": fichier,
        "titre": str(entree.get("titre") or "") or humaniser(fichier),
        "reference": str(entree.get("reference") or ""),
        "pages": max(0, pages),
        "notes": str(entree.get("notes") or ""),
    })
    return out


def enregistrer(ship_folder: str, cat: dict) -> str:
    """Écrit `plans/catalogue.json`. Rend le chemin écrit, ou "" si le dossier
    n'est pas inscriptible — auquel cas on n'a rien perdu d'autre que le
    catalogue : les plans, eux, sont dans `plans/`."""
    dossier = dossier_plans(ship_folder)
    path = chemin_catalogue(ship_folder)
    data = {"plans": [_normaliser(e) for e in (cat or {}).get("plans", [])]}
    for cle, val in (cat or {}).items():        # on ne jette rien d'inconnu
        if cle != "plans":
            data[cle] = val
    try:
        os.makedirs(dossier, exist_ok=True)
        with ecriture_atomique(path) as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except OSError:
        return ""
    return path


def entree(cat: dict, fichier: str):
    """L'entrée de ce fichier dans le catalogue, ou None."""
    nom = os.path.basename(str(fichier or "").replace("\\", "/"))
    for e in (cat or {}).get("plans", []):
        if e.get("fichier") == nom:
            return e
    return None


# ------------------------------------------------------------------ titres
def humaniser(nom_fichier: str) -> str:
    """« C900630006F_Cargo_hold_layout.pdf » → « Cargo hold layout ».

    Le nom d'un plan de chantier est un matricule suivi d'un intitulé anglais
    collé aux tirets bas. On rend l'intitulé lisible ; le matricule, lui,
    devient la RÉFÉRENCE (`reference_et_titre`), affichée à part."""
    base = os.path.splitext(os.path.basename(str(nom_fichier or "")))[0]
    texte = re.sub(r"[_\-]+", " ", base).strip()
    texte = re.sub(r"\s+", " ", texte)
    if not texte:
        return base
    return texte[0].upper() + texte[1:]


def reference_et_titre(nom_fichier: str):
    """(référence, titre) déduits du nom de fichier.

    Sur un nom du chantier — « C900630006F_Cargo_hold_layout.pdf » — la
    référence est « C900-6300-06 » et le titre « Cargo hold layout ». Sur
    n'importe quel autre nom, la référence est vide et le titre est le nom
    humanisé : on ne devine pas un matricule là où il n'y en a pas."""
    base = os.path.splitext(os.path.basename(str(nom_fichier or "")))[0]
    m = MOTIF_CHANTIER.match(base)
    if not m:
        return "", humaniser(base)
    prefixe, quatre, deux, _revision, reste = m.groups()
    reference = f"{prefixe.upper()}-{quatre}-{deux}"
    titre = humaniser(reste) or humaniser(base)
    return reference, titre


def titre_par_defaut(chemin: str) -> str:
    """Le titre à proposer pour ce PDF, quand personne n'en donne un.

    CHOIX TRANCHÉ : sur un nom de plan du chantier, c'est l'intitulé tiré du
    NOM DE FICHIER qui gagne, pas les métadonnées du PDF. Le plan d'ensemble
    du navire de référence s'annonce « Présentation » dans ses métadonnées (le nom du
    gabarit qui l'a exporté) là où son nom de fichier dit « General
    arrangement » : entre un titre juste et un titre officiel mais faux, on
    prend le juste. Hors motif chantier, les métadonnées passent devant — un
    « scan_0001.pdf » n'a rien à dire, son PDF peut-être."""
    fichier = os.path.basename(str(chemin or "").replace("\\", "/"))
    reference, titre_nom = reference_et_titre(fichier)
    if reference:
        return titre_nom
    from . import pdf_plan
    try:
        meta = pdf_plan.titre_document(chemin)
    except Exception:
        meta = ""
    return meta or titre_nom


# ------------------------------------------------------------------ gestes
def ajouter(ship_folder: str, pdf_path: str, titre: str | None = None) -> dict:
    """Range un PDF dans `plans/` et l'inscrit au catalogue. Rend l'entrée.

    Le fichier est copié par `pdf_plan.ranger_pdf` — la MÊME logique que
    l'import d'une page dans une vue, pour que les deux chemins ne puissent
    pas ranger le même plan à deux endroits. Un plan déjà inscrit n'est pas
    dupliqué : son nombre de pages est remis à jour (le chantier a pu envoyer
    une révision) et son titre n'est écrasé que si on en donne un."""
    from . import pdf_plan
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"Plan introuvable : {pdf_path}")
    dest = pdf_plan.ranger_pdf(pdf_path, ship_folder)
    fichier = os.path.basename(dest)
    try:
        pages = int(pdf_plan.page_count(dest))
    except Exception:
        # PDF illisible : on l'inscrit quand même (le bord voit alors
        # « 0 page » et sait que quelque chose cloche) plutôt que de le
        # laisser disparaître sans un mot
        pages = 0
    reference, _titre_auto = reference_et_titre(fichier)
    if not titre:
        titre = titre_par_defaut(dest)
    cat = charger(ship_folder)
    deja = entree(cat, fichier)
    if deja is not None:
        deja["pages"] = pages
        if titre:
            deja["titre"] = titre
        if reference and not deja.get("reference"):
            deja["reference"] = reference
        enregistrer(ship_folder, cat)
        return deja
    e = _normaliser({"fichier": fichier, "titre": titre,
                     "reference": reference, "pages": pages, "notes": ""})
    cat.setdefault("plans", []).append(e)
    enregistrer(ship_folder, cat)
    return e


def retirer(ship_folder: str, fichier: str, supprimer_fichier: bool = False) -> bool:
    """Retire un plan du catalogue. Rend True si quelque chose a été retiré.

    Le PDF reste dans `plans/` par défaut : le retirer du catalogue, c'est
    dire « ne me le propose plus », pas « jette-le » — les vues qui s'en
    servent continuent d'en relire les sommets pour l'accroche. Il faut le
    demander (`supprimer_fichier=True`) pour l'effacer du disque."""
    nom = os.path.basename(str(fichier or "").replace("\\", "/"))
    cat = charger(ship_folder)
    reste = [e for e in cat.get("plans", []) if e.get("fichier") != nom]
    trouve = len(reste) != len(cat.get("plans", []))
    cat["plans"] = reste
    enregistrer(ship_folder, cat)
    if trouve and supprimer_fichier:
        try:
            os.remove(chemin_du_plan(ship_folder, nom))
        except OSError:
            pass
    return trouve


def renommer(ship_folder: str, fichier: str, titre: str,
             reference: str | None = None, notes: str | None = None):
    """Change le titre (et, si on le donne, la référence ou les notes) d'un
    plan. Rend l'entrée, ou None si le plan n'est pas au catalogue."""
    cat = charger(ship_folder)
    e = entree(cat, fichier)
    if e is None:
        return None
    if titre is not None:
        e["titre"] = str(titre).strip() or e["titre"]
    if reference is not None:
        e["reference"] = str(reference).strip()
    if notes is not None:
        e["notes"] = str(notes)
    enregistrer(ship_folder, cat)
    return e


# ------------------------------------------------------------- utilisations
def _vues_du_projet(project):
    """[(libellé de la vue, Calibrated)] — le profil puis chaque pont."""
    if project is None:
        return []
    vues = []
    profil = getattr(project, "profile", None)
    if profil is not None:
        vues.append(("profil", profil))
    decks = project.sorted_decks() if hasattr(project, "sorted_decks") \
        else (getattr(project, "decks", None) or [])
    for d in decks:
        plan = getattr(d, "plan", None)
        if plan is not None:
            vues.append((f"pont {d.name}", plan))
    return vues


def utilisations(cat: dict, project) -> dict:
    """{fichier: [(page, vue)]} — qui se sert de quel plan, DÉDUIT des vues.

    `page` est le numéro à partir de 0, celui de `Calibrated.pdf_page` ; la
    fenêtre l'affiche à partir de 1. Tout plan du catalogue figure dans le
    résultat, avec une liste vide s'il ne sert encore à rien : la liste de la
    fenêtre peut donc s'écrire d'une seule lecture."""
    out = {e.get("fichier"): [] for e in (cat or {}).get("plans", [])
           if e.get("fichier")}
    for nom_vue, cal in _vues_du_projet(project):
        pdf = getattr(cal, "pdf_path", "")
        if not pdf:
            continue
        fichier = os.path.basename(str(pdf).replace("\\", "/"))
        out.setdefault(fichier, []).append((int(getattr(cal, "pdf_page", 0) or 0),
                                            nom_vue))
    return out


def phrase_utilisation(uses) -> str:
    """« utilisé par : profil (page 1), pont Inférieur (page 3) », ou "" ."""
    if not uses:
        return ""
    bouts = [f"{vue} (page {int(page) + 1})" for page, vue in uses]
    return "utilisé par : " + ", ".join(bouts)


def synchroniser(ship_folder: str, project) -> dict:
    """Inscrit au catalogue les PDF de `plans/` qu'une vue utilise sans qu'ils
    y figurent, et rend le catalogue.

    C'est le filet du catalogue : un navire créé avant lui, ou un plan importé
    par la boîte de fichiers, ne doit pas rester invisible au catalogue alors
    que son PDF est bel et bien dans le dossier du navire. On n'inscrit que
    ce qui est DANS `plans/` — un PDF resté sur le disque de l'utilisateur
    n'appartient pas au navire, et l'inscrire promettrait un plan qui
    disparaîtra au premier changement de machine."""
    cat = charger(ship_folder)
    if not ship_folder:
        return cat
    plans = os.path.abspath(dossier_plans(ship_folder))
    change = False
    for _nom_vue, cal in _vues_du_projet(project):
        pdf = getattr(cal, "pdf_path", "")
        if not pdf:
            continue
        chemin = os.path.abspath(str(pdf))
        if os.path.dirname(chemin) != plans or not os.path.exists(chemin):
            continue
        fichier = os.path.basename(chemin)
        if entree(cat, fichier) is not None:
            continue
        from . import pdf_plan
        try:
            pages = int(pdf_plan.page_count(chemin))
        except Exception:
            pages = 0
        reference, _ = reference_et_titre(fichier)
        titre = titre_par_defaut(chemin)
        cat.setdefault("plans", []).append(_normaliser(
            {"fichier": fichier, "titre": titre, "reference": reference,
             "pages": pages, "notes": ""}))
        change = True
    if change:
        enregistrer(ship_folder, cat)
    return cat
