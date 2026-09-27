# -*- coding: utf-8 -*-
"""Le regroupement des capacités par nature — « Fresh water », « Gas oil »…

C'est une **donnée du navire**, pas une règle du logiciel : elle se règle à la
création du navire (colonne `Groupe` de `capacites.csv`) et se lit partout de
la même façon — relevé des capacités, bilan des poids, sorties imprimées.

Faute de colonne `Groupe`, le groupe est déduit du `Type` du dossier par une
table de synonymes ouverte : chaque chantier a son vocabulaire, et un type
inconnu devient un groupe portant son propre nom plutôt qu'une erreur. Rien
n'est inventé — au pire, un groupe d'un seul membre.

L'**ordre** des groupes est celui de leur première apparition dans la liste du
dossier : c'est l'ordre du navire, pas un ordre alphabétique décidé ici.

Pas de Qt, pas de valeur propre à un navire.
"""
from __future__ import annotations

# type (comparé sans casse, par inclusion) → nom de groupe
SYNONYMES = (
    ("water ballast", "Ballast"),
    ("sea water", "Ballast"),
    ("seawater", "Ballast"),
    ("eau de mer", "Ballast"),
    ("ballast", "Ballast"),
    ("freshwater", "Eau douce"),
    ("fresh water", "Eau douce"),
    ("eau douce", "Eau douce"),
    ("gasoil", "Combustible"),
    ("gas oil", "Combustible"),
    ("diesel", "Combustible"),
    ("fuel", "Combustible"),
    ("mdo", "Combustible"),
    ("hfo", "Combustible"),
    # « sludge oil », « oily bilge » : les résidus passent AVANT « oil »,
    # sans quoi l'inclusion de « oil » les rangeait dans les huiles propres
    ("sludge", "Boues"),
    ("bilge", "Eaux usées"),
    ("lub", "Huiles"),
    ("hydraul", "Huiles"),
    ("huile", "Huiles"),
    ("oil", "Huiles"),
    ("sewage", "Eaux usées"),
    ("blackwater", "Eaux usées"),
    ("black water", "Eaux usées"),
    ("greywater", "Eaux usées"),
    ("grey water", "Eaux usées"),
    ("eaux grises", "Eaux usées"),
    ("eaux noires", "Eaux usées"),
    ("urea", "Urée"),
    ("urée", "Urée"),
    ("lng", "GNL"),
    ("gnl", "GNL"),
)

# proposés à la création du navire ; la liste reste ouverte
GROUPES_USUELS = ["Combustible", "Eau douce", "Ballast", "Huiles",
                  "Eaux usées", "Urée", "Boues", "GNL", "Divers"]

AUTRES = "Divers"


def groupe_de_meta(meta) -> str:
    """Groupe d'une capacité, depuis sa ligne de `capacites.csv`."""
    explicite = str((meta or {}).get("Groupe", "") or "").strip()
    if explicite:
        return explicite
    t = str((meta or {}).get("Type", "") or "").strip()
    bas = t.lower()
    for cle, nom in SYNONYMES:
        if cle in bas:
            return nom
    return t or AUTRES


def groupe_de(cap) -> str:
    """Groupe d'une `core.navire.Capacity`."""
    return groupe_de_meta(getattr(cap, "meta", None))


def grouper(noms, capacites):
    """[(groupe, [nom, ...])] dans l'ordre du dossier.

    `noms` est la suite des capacités telle qu'on veut l'afficher (l'ordre du
    relevé) ; `capacites` le dictionnaire du navire. Une capacité que le navire
    ne connaît plus est rangée à part, en fin de liste : elle doit rester
    visible, sans se faire compter dans un groupe.
    """
    ordre, par_groupe = [], {}
    orphelines = []
    for nom in noms:
        cap = (capacites or {}).get(nom)
        if cap is None:
            orphelines.append(nom)
            continue
        g = groupe_de(cap)
        if g not in par_groupe:
            par_groupe[g] = []
            ordre.append(g)
        par_groupe[g].append(nom)
    out = [(g, par_groupe[g]) for g in ordre]
    if orphelines:
        out.append(("Capacités absentes du navire", orphelines))
    return out
