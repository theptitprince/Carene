# -*- coding: utf-8 -*-
"""Le bilan des poids, poste par poste — le tableau qu'on trouve dans tout
recueil de stabilité et dans LOCOPIAS : chaque ligne avec son poids, ses trois
centres et sa carène liquide ; des sous-totaux par groupe ; le total qui
alimente le calcul.

Les chiffres sont exactement ceux que le moteur additionne (`Condition.totals`)
— même convention de carène liquide, même lecture des jauges. Ce module ne
calcule rien de nouveau, il montre.

Pas de Qt ici.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .core.groupes import groupe_de


def densite_texte(v):
    """Une densité écrite en français (virgule, trois décimales) : 1,025.

    La MÊME écriture partout — bilan, tableau des capacités, rapports,
    messages — parce que la densité se tape autant qu'elle se lit : ce que
    l'officier voit doit être exactement ce qu'il peut retaper. Trois
    décimales suffisent (1,025 pour l'eau de mer, 0,840 pour un gazole) et
    c'est aussi la tolérance de `TankFill.densite_modifiee`."""
    return "—" if v is None else f"{float(v):.3f}".replace(".", ",")


# raccourci interne : ce module l'emploie à chaque ligne de capacité
_d = densite_texte


@dataclass
class Ligne:
    nom: str
    poids_t: float
    lcg_m: float
    tcg_m: float
    vcg_m: float
    fsm_tm: float = 0.0
    detail: str = ""          # « sonde 1,20 m · 45 % », « 45 charges », …
    alerte: str = ""          # slack, capacité orpheline…


@dataclass
class Groupe:
    nom: str
    lignes: list = field(default_factory=list)

    @property
    def poids_t(self):
        return sum(l.poids_t for l in self.lignes)

    @property
    def fsm_tm(self):
        return sum(l.fsm_tm for l in self.lignes)

    def centres(self):
        w = self.poids_t
        if w <= 0:
            return (0.0, 0.0, 0.0)
        return (sum(l.poids_t * l.lcg_m for l in self.lignes) / w,
                sum(l.poids_t * l.tcg_m for l in self.lignes) / w,
                sum(l.poids_t * l.vcg_m for l in self.lignes) / w)


@dataclass
class Bilan:
    groupes: list = field(default_factory=list)

    @property
    def poids_t(self):
        return sum(g.poids_t for g in self.groupes)

    @property
    def fsm_tm(self):
        return sum(g.fsm_tm for g in self.groupes)

    def centres(self):
        w = self.poids_t
        if w <= 0:
            return (0.0, 0.0, 0.0)
        return (sum(g.poids_t * g.centres()[0] for g in self.groupes) / w,
                sum(g.poids_t * g.centres()[1] for g in self.groupes) / w,
                sum(g.poids_t * g.centres()[2] for g in self.groupes) / w)


def construire(condition, navire, project) -> Bilan:
    """Le bilan de cette condition, dans l'ordre : lège, liquides par nature,
    cales, matériel du bord, poids divers."""
    b = Bilan()
    if condition.inclure_lege and navire is not None:
        lege = navire.lege
        g = Groupe("Navire lège")
        g.lignes.append(Ligne("Navire lège", float(lege["masse_t"]), float(lege["lcg_m"]),
                              float(lege.get("tcg_m", 0.0)), float(lege["vcg_m"]),
                              detail=str(lege.get("base", "") or "dossier du navire")))
        b.groupes.append(g)

    # liquides : un groupe par nature, dans l'ordre du dossier
    groupes = {}
    convention = getattr(navire, "convention_fsm", "max") if navire is not None else "max"
    caps = getattr(navire, "capacities", {}) or {}
    for t in condition.tanks:
        # la capacité TELLE QUE CHARGÉE : densité du point si elle est relevée,
        # densité du dossier sinon. Poids, FSM tabulé et FSM maximal en sortent
        # tous les trois à la même échelle (core.navire.Capacity.avec_densite)
        cap = t.capacite_chargee(navire)
        ligne = t.ligne(navire)
        if cap is None or ligne is None:
            if t.valeur:
                g = groupes.setdefault("Capacités orphelines", Groupe("Capacités orphelines"))
                g.lignes.append(Ligne(t.capacite, 0.0, 0.0, 0.0, 0.0,
                                      alerte="capacité inconnue du navire : hors calcul"))
            continue
        w = float(ligne["Poids_t"])
        if w <= 0:
            continue
        pc = t.fill_pc(navire)
        fsm = 0.0
        alerte = ""
        if 0.0 < pc < 100.0:
            fsm = float(ligne.get("FSM_tm", cap.fsm_max_tm)) if convention == "reel" else cap.fsm_max_tm
            alerte = "carène liquide"
        nom_g = groupe_de(cap)
        g = groupes.setdefault(nom_g, Groupe(nom_g))
        # La densité figure TOUJOURS au détail : un poids imprimé sans la
        # densité qui l'a produit est illisible — on ne peut pas remonter du
        # tonnage au volume relevé. Quand elle s'écarte du dossier, on le dit.
        detail_d = f" · d {_d(cap.density)}"
        if t.densite_modifiee(navire):
            detail_d += f" (dossier : {_d(cap.densite_dossier)})"
        g.lignes.append(Ligne(
            t.capacite, w, float(ligne["LCG_m"]), float(ligne.get("TCG_m", 0.0)),
            float(ligne.get("VCG_m", 0.0)), fsm,
            detail=(f"{'sonde' if t.mesure == 'sonde' else t.mesure} {t.valeur:g}"
                    f"{' m' if t.mesure == 'sonde' else (' m³' if t.mesure == 'volume' else ' %')}"
                    f" · {pc:.0f} % · {float(ligne.get('Volume_m3', 0.0)):.1f} m³"
                    + detail_d),
            alerte=alerte))
    b.groupes.extend(groupes.values())

    # cales : la MARCHANDISE d'un côté, le MATÉRIEL DU BORD de l'autre.
    # Le total ne bouge pas d'un gramme — c'est la même somme, séparée en deux
    # pour que l'officier voie d'un coup d'œil ce qui est du fret et ce qui
    # est l'engin du bord qu'il retrouvera au prochain voyage.
    lignes = condition.lignes_cargaison(project)
    if lignes:
        g = Groupe("Cales")
        for code, nom, w, lcg, tcg, vcg, n in lignes:
            g.lignes.append(Ligne(f"{code} {nom}".strip(), w, lcg, tcg, vcg,
                                  detail=f"{n} charge(s)"))
        b.groupes.append(g)

    materiel = condition.lignes_materiel(project)
    if materiel:
        g = Groupe("Matériel du bord")
        for code, nom, w, lcg, tcg, vcg, n in materiel:
            g.lignes.append(Ligne(f"{code} {nom}".strip(), w, lcg, tcg, vcg,
                                  detail=f"{n} engin(s) du bord — pas de la "
                                         "marchandise, jamais au manifeste"))
        b.groupes.append(g)

    # poids divers
    extras = [e for e in condition.extras if e.poids_t]
    if extras:
        g = Groupe("Poids divers")
        for e in extras:
            g.lignes.append(Ligne(e.nom, e.poids_t, e.lcg_m, e.tcg_m, e.vcg_m))
        b.groupes.append(g)
    return b
