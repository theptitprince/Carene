# -*- coding: utf-8 -*-
"""L'écriture protégée des fichiers du bord (2.21.0, D-77).

Un point du journal, `navire.json`, `geometrie.json`, le catalogue : tout cela
s'écrivait par `open(chemin, "w")` puis `json.dump`. Une coupure de courant,
un NAS qui décroche ou un poste qu'on éteint PENDANT l'écriture laissait un
fichier tronqué — et un point tronqué disparaissait du journal sans un mot
(revue du 24/09/2026, P-2). Sur un partage réseau, écrire quelques milliers
de colis prend assez longtemps pour que ce ne soit pas une vue de l'esprit.

Trois gestes, toujours dans cet ordre :

1. tout est écrit dans un fichier PROVISOIRE, à côté du vrai (même disque,
   pour que le renommage final soit atomique), puis forcé sur le disque
   (`fsync`) ;
2. la version précédente est copiée en `<fichier>.bak` — une seule
   génération : c'est un filet, pas un historique ;
3. le provisoire REMPLACE le vrai d'un seul geste (`os.replace`).

Si quoi que ce soit échoue avant le troisième geste, le vrai fichier n'a pas
été touché et le provisoire est effacé. Au pire, on perd la modification en
cours ; jamais le fichier.

`lire_json_ou_bak` fait le chemin inverse : un fichier illisible est relu dans
sa copie `.bak`, et l'appelant sait qu'il l'a été.
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import time

SUFFIXE_BAK = ".bak"


def _remplacer(provisoire: str, chemin: str, essais: int = 5):
    """`os.replace`, avec quelques essais : sous Windows, un antivirus ou
    l'indexation tient parfois le fichier une fraction de seconde."""
    for i in range(essais):
        try:
            os.replace(provisoire, chemin)
            return
        except PermissionError:
            if i == essais - 1:
                raise
            time.sleep(0.2 * (i + 1))


@contextlib.contextmanager
def ecriture_atomique(chemin: str, mode: str = "w", encoding: str | None = "utf-8",
                      newline: str | None = None, bak: bool = True):
    """`with ecriture_atomique(chemin) as f: ...` — s'emploie comme `open`.

    Le vrai fichier n'est remplacé qu'à la sortie SANS erreur du bloc."""
    chemin = os.fspath(chemin)
    dossier = os.path.dirname(os.path.abspath(chemin))
    os.makedirs(dossier, exist_ok=True)
    provisoire = f"{chemin}.{os.getpid()}.tmp"
    binaire = "b" in mode
    f = open(provisoire, mode, **({} if binaire else
                                  {"encoding": encoding, "newline": newline}))
    try:
        yield f
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass                    # certains partages ne le permettent pas
        f.close()
        if bak and os.path.exists(chemin):
            try:
                shutil.copy2(chemin, chemin + SUFFIXE_BAK)
            except OSError:
                pass                # le filet manque, pas l'écriture
        _remplacer(provisoire, chemin)
    except BaseException:
        try:
            f.close()
        except Exception:           # noqa: BLE001
            pass
        try:
            os.remove(provisoire)
        except OSError:
            pass
        raise


def ecrire_json(chemin: str, donnees, bak: bool = True, **options):
    """Écrit `donnees` en JSON, de façon protégée. Mêmes options que
    `json.dump` (par défaut : UTF-8 lisible, indentation d'une espace)."""
    options.setdefault("ensure_ascii", False)
    options.setdefault("indent", 1)
    with ecriture_atomique(chemin, bak=bak) as f:
        json.dump(donnees, f, **options)


def lire_json_ou_bak(chemin: str):
    """(données, "fichier" | "bak") — le fichier, ou sa copie `.bak` s'il est
    illisible. Lève l'erreur du fichier si la copie manque ou l'est aussi."""
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f), "fichier"
    except (OSError, ValueError) as e:
        premiere = e
    try:
        with open(chemin + SUFFIXE_BAK, encoding="utf-8") as f:
            return json.load(f), "bak"
    except (OSError, ValueError):
        raise premiere
