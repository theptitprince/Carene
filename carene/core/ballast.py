# -*- coding: utf-8 -*-
"""Solutionneur de ballastage.

On choisit les ballasts sur lesquels on accepte de jouer, on dit si l'on peut
embarquer ou rejeter de l'eau ou seulement transférer d'une capacité à l'autre,
et le module cherche la meilleure répartition possible.

**Meilleure au sens de quoi**, dans l'ordre : redresser la gîte, tenir
l'assiette visée, garder le meilleur GM corrigé, embarquer le moins d'eau.
Ces quatre buts sont agrégés en un score unique (voir `Reglages`), dont les
poids sont explicites et modifiables : rien n'est caché dans une constante.

Aucune donnée navire n'est codée ici : masses, centres et carènes liquides
viennent des tables de jaugeage du navire, exactement comme le calcul principal
— y compris la convention de carène liquide déclarée par le dossier
(navire.json / « convention_fsm ») : le **FSM réel du remplissage** pour
le navire de référence, comme son recueil approuvé (D-14), le **FSM maximal** — plus
conservatif — pour un dossier qui le demande ou qui ne déclare rien.

Deux précisions sur les chiffres rendus :

- pendant la recherche, la gîte est estimée par l'approximation des petits
  angles (tan θ = TCG / GM corrigé), qui suffit à **comparer** des milliers de
  configurations. La gîte du départ et celle de la solution retenue sont, elles,
  recalculées exactement sur les pantocarènes ; l'écart entre les deux est de
  l'ordre du centième de degré, mais il existe ;
- une configuration qui sort du domaine des tables n'est jamais présentée comme
  exploitable. Elle reste cependant évaluée, avec une pénalité croissant avec
  l'écart au domaine : sans cela, un chargement déjà hors tables ne fournirait
  aucune pente et le solveur ne saurait pas dans quel sens ramener le navire.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from . import hydrostatics, stability
from .condition import Condition, TankState


# --------------------------------------------------------------------- entrées
@dataclass
class Reglages:
    """Ce que l'officier accepte de faire, et ce qu'il cherche."""

    tanks: list = field(default_factory=list)   # capacités sur lesquelles jouer
    transfert_seul: bool = False    # True : le volume d'eau total est conservé
    assiette_cible_m: float = None  # None : ne pas contraindre l'assiette
    # Gîte visée en degrés (bâbord négatif, comme partout). 0 : navire droit,
    # ce qu'on veut presque toujours ; None : ne pas contraindre la gîte
    # (chercher seulement l'assiette, le GM et l'économie d'eau). Le bord a
    # demandé que « gîte nulle » soit une consigne visible et choisie, pas un
    # sous-entendu du score.
    gite_cible_deg: float = 0.0
    pas_pc: float = 5.0             # granularité de la recherche (% de remplissage)
    affiner: bool = True            # réglage fin continu après la recherche

    # Poids du score. Ordre voulu : gîte, puis assiette, puis GM, puis eau.
    # Ordres de grandeur sur le navire de référence : 1° de bande = 50 ; 10 cm d'écart
    # d'assiette = 2 ; 10 cm de GM gagné = 0,5 ; 100 m³ d'eau = 0,2.
    poids_gite: float = 50.0
    poids_assiette: float = 20.0
    # En deçà, l'objectif est considéré atteint : sans cette zone morte, le
    # solveur irait chercher le dixième de degré au prix d'un demi-mètre cube
    # dans un ballast — une manœuvre que personne ne commande à bord.
    tolerance_gite_deg: float = 0.2
    tolerance_assiette_m: float = 0.02
    poids_gm: float = 5.0
    poids_eau: float = 0.002
    # « Éviter les ballasts partiels, mais les autoriser si nécessaire » : le
    # FSM les pénalise déjà par le GM ; ce terme rend la préférence explicite.
    penalite_slack: float = 0.5
    # plancher de GM sous lequel la pénalité devient forte. None = dérivé des
    # critères du navire (le plus exigeant de IS2008 et NR500 s'il est actif) ;
    # 0,15 m n'est que le défaut IMO, pas une constante universelle.
    gm_mini_m: float = None
    penalite_gm_mini: float = 100.0

    def gm_plancher(self, navire):
        if self.gm_mini_m is not None:
            return self.gm_mini_m
        criteres = getattr(navire, "criteres", {}) or {}
        seuils = [float(criteres.get("is2008_general", {})
                        .get("gm0_corrige_m_min", 0.15))]
        nr500 = criteres.get("nr500_voile")
        if nr500:
            seuils.append(float(nr500.get("gm0_corrige_m_min", 0.30)))
        return max(seuils)


@dataclass
class Etat:
    """Une configuration de ballastage et ce qu'elle donne."""

    remplissages: dict = field(default_factory=dict)   # nom -> %
    poids_t: float = 0.0
    lcg_m: float = 0.0
    tcg_m: float = 0.0
    vcg_m: float = 0.0
    fsm_total_tm: float = 0.0
    assiette_m: float = 0.0
    tirant_eau_m: float = 0.0
    te_ar_m: float = None
    te_av_m: float = None
    gm_corrige_m: float = 0.0
    gite_deg: float = 0.0
    gite_exacte: bool = False       # False : approximation des petits angles
    eau_m3: float = 0.0
    slack: list = field(default_factory=list)
    dans_domaine: bool = True
    ecart_domaine: float = 0.0      # de combien on sort des tables (m)
    score: float = float("inf")


@dataclass
class Rapport:
    depart: Etat = None
    arrivee: Etat = None
    operations: list = field(default_factory=list)   # (nom, avant_m3, après_m3)
    evaluations: int = 0
    duree_s: float = 0.0
    messages: list = field(default_factory=list)


# ------------------------------------------------------------------ ballasts
# Types reconnus comme ballast quand le dossier ne le déclare pas
# explicitement. Comparaison insensible à la casse. Un dossier peut toujours
# trancher lui-même : colonne « Ballast » (0/1) dans capacites.csv.
TYPES_BALLAST = {"sea water", "seawater", "water ballast", "ballast",
                 "ballast water", "eau de mer", "wb", "sw"}


def est_ballast(cap):
    """Cette capacité est-elle jouable en ballastage ?

    Priorité au dossier : si capacites.csv porte une colonne « Ballast », elle
    fait foi. Sinon, le type est comparé (sans casse) à une liste de synonymes
    usuels — « Sea Water » n'est que le vocabulaire du dossier de référence, un
    autre chantier écrira « Water Ballast » ou « Eau de mer »."""
    v = cap.meta.get("Ballast")
    if v is not None and str(v).strip() != "":
        return str(v).strip().lower() in ("1", "true", "oui", "yes", "x")
    return str(cap.meta.get("Type", "")).strip().lower() in TYPES_BALLAST


def ballasts_du_navire(navire, types=None):
    """Capacités jouables en ballastage : déclarées ballast (voir
    `est_ballast`) ET munies d'une table de jaugeage. `types` (facultatif)
    remplace la liste de synonymes par un jeu exact de types."""
    out = []
    for nom, cap in navire.capacities.items():
        if not cap.jauge_rows:
            continue
        if types is not None:
            if str(cap.meta.get("Type", "")).strip() in types:
                out.append(nom)
        elif est_ballast(cap):
            out.append(nom)
    return sorted(out)


class _Table:
    """Lignes de jaugeage précalculées sur la grille de remplissage.

    Le solveur évalue des milliers de configurations : interpoler la table à
    chaque fois coûterait plus cher que le calcul d'équilibre lui-même.

    `densites` : nom de capacité -> densité relevée au point (t/m³), ou rien
    pour celle du dossier. Un ballast déjà renseigné au point pèse ce qu'il
    pèse RÉELLEMENT — le bord ballaste aussi en eau saumâtre — et un ballast
    que le solveur remplit lui-même garde cette densité si elle est saisie,
    parce que c'est la même prise d'eau : c'est bien la densité du point, pas
    celle du dossier, qu'il faut compter pour l'eau qu'on embarque.
    """

    def __init__(self, navire, noms, pas_pc, densites=None):
        densites = densites or {}
        self.densites = dict(densites)
        self.cap = {n: navire.capacity(n).avec_densite(densites.get(n))
                    for n in noms}
        self.niveaux = _grille(pas_pc)
        # même convention de carène liquide que le calcul principal
        self.fsm_reel = getattr(navire, "convention_fsm", "max") == "reel"
        self.lignes = {}
        for n, c in self.cap.items():
            self.lignes[n] = {p: self._ligne(c, p) for p in self.niveaux}

    def _ligne(self, cap, pc):
        r = cap.at_fill_pc(pc)
        # VCG solide : la carène liquide est portée par le FSM, une seule fois
        # (voir carene.core.condition.Condition.totals)
        if not 0.0 < pc < 100.0:
            fsm = 0.0
        elif self.fsm_reel:
            fsm = float(r.get("FSM_tm", cap.fsm_max_tm))
        else:
            fsm = cap.fsm_max_tm
        return (r["Poids_t"], r["LCG_m"], r.get("TCG_m", 0.0),
                r.get("VCG_m", 0.0), r["Volume_m3"], fsm)

    def ligne(self, nom, pc):
        """Ligne au remplissage demandé, calculée à la volée hors grille."""
        cache = self.lignes[nom]
        if pc in cache:
            return cache[pc]
        val = self._ligne(self.cap[nom], pc)
        cache[pc] = val
        return val

    def volume_max(self, nom):
        return self.ligne(nom, 100.0)[4]


def _grille(pas_pc):
    """Niveaux essayés par la recherche : toujours vide et plein — un ballast
    pressé ou vide ne fait pas de carène liquide — plus les paliers du pas."""
    pas = max(0.5, float(pas_pc))
    n = [0.0]
    v = pas
    while v < 100.0 - 1e-9:
        n.append(round(v, 3))
        v += pas
    n.append(100.0)
    return n


# ------------------------------------------------------------------ évaluation
class _Evaluateur:
    """Calcule l'état du navire pour une configuration de ballasts.

    La partie fixe de la condition (lège, cargaison, soutes non retenues) est
    agrégée une fois pour toutes en poids et moments : chaque évaluation ne
    refait que la somme des ballasts choisis, puis l'équilibre.
    """

    def __init__(self, navire, cond, reglages, table):
        self.nav = navire
        self.reg = reglages
        self.tab = table
        self.n = 0
        # plancher de GM du NAVIRE (critères de son dossier), pas du code
        self.gm_mini = reglages.gm_plancher(navire)

        noms = set(reglages.tanks)
        autres = [t for t in cond.tanks if t.capacite not in noms]
        fixe = Condition(navire=navire, cargo=list(cond.cargo), tanks=autres,
                          inclure_lege=cond.inclure_lege)
        w, lcg, tcg, vcg, fsm = fixe.totals()
        self.w0, self.ml0, self.mt0, self.mv0, self.fsm0 = (
            w, w * lcg, w * tcg, w * vcg, fsm)

    def etat(self, remplissages, exact=False):
        self.n += 1
        w, ml, mt, mv = self.w0, self.ml0, self.mt0, self.mv0
        fsm = self.fsm0
        eau = 0.0
        slack = []
        for nom, pc in remplissages.items():
            p, lcg, tcg, vcg, vol, f = self.tab.ligne(nom, pc)
            w += p
            ml += p * lcg
            mt += p * tcg
            mv += p * vcg
            fsm += f
            eau += vol
            if f > 0.0:
                slack.append(nom)

        e = Etat(remplissages=dict(remplissages), eau_m3=eau, slack=slack,
                 fsm_total_tm=fsm)
        if w <= 0:
            e.score = float("inf")
            return e
        e.poids_t, e.lcg_m = w, ml / w
        e.tcg_m, e.vcg_m = mt / w, mv / w

        try:
            eq = hydrostatics.solve_equilibrium(self.nav, e.poids_t, e.lcg_m)
        except Exception:
            e.score = float("inf")
            return e
        e.assiette_m, e.tirant_eau_m = eq.trim_m, eq.draft_m
        e.te_ar_m = (eq.hydro or {}).get("TE_AR_m")
        e.te_av_m = (eq.hydro or {}).get("TE_AV_m")
        e.dans_domaine = bool(eq.converged and eq.dans_domaine)
        e.ecart_domaine = _ecart_domaine(self.nav, eq)

        kmt = self.nav.hydro.value(eq.trim_m, eq.draft_m, "KMt_m")
        e.gm_corrige_m = kmt - e.vcg_m - fsm / e.poids_t

        # sans pantocarènes, `angle_equilibre` lèverait : on se contente de
        # la gîte approchée, et l'état le dit (gite_exacte reste False)
        exact = exact and getattr(self.nav, "a_pantocarenes", False)
        if exact:
            a = stability.angle_equilibre(self.nav, eq, e.vcg_m, e.tcg_m, fsm)
            # None = pas d'équilibre stable : on ne le maquille pas en 0°
            e.gite_deg = a if a is not None else float("nan")
            e.gite_exacte = True
        else:
            # approximation des petits angles, suffisante pour comparer des
            # configurations entre elles ; l'angle exact est recalculé sur la
            # solution retenue (tan θ = TCG / GM)
            gm = e.gm_corrige_m
            e.gite_deg = (math.degrees(math.atan2(e.tcg_m, gm))
                          if gm > 1e-3 else math.copysign(90.0, e.tcg_m or 1.0))
        e.score = self._score(e)
        return e

    def _score(self, e):
        r = self.reg
        if not e.dans_domaine:
            # Une solution extrapolée n'a aucune valeur : elle est toujours
            # moins bonne que n'importe quelle solution valable. On garde
            # cependant une pente vers le domaine — sans quoi, partant d'un
            # chargement déjà hors tables, tout se vaudrait à l'infini et le
            # solveur ne saurait plus dans quel sens ramener le navire.
            return 1e6 + 1e3 * e.ecart_domaine
        if e.gite_deg != e.gite_deg:           # NaN : aucun équilibre stable
            return float("inf")
        s = 0.0
        if r.gite_cible_deg is not None:
            gite = abs(e.gite_deg - r.gite_cible_deg)
            s += r.poids_gite * max(0.0, gite - r.tolerance_gite_deg)
        if r.assiette_cible_m is not None:
            ecart = abs(e.assiette_m - r.assiette_cible_m)
            s += r.poids_assiette * max(0.0, ecart - r.tolerance_assiette_m)
        s -= r.poids_gm * e.gm_corrige_m
        if e.gm_corrige_m < self.gm_mini:
            s += r.penalite_gm_mini * (self.gm_mini - e.gm_corrige_m)
        s += r.poids_eau * e.eau_m3
        s += r.penalite_slack * len(e.slack)
        return s


def _ecart_domaine(navire, eq):
    """De combien (en mètres cumulés) l'équilibre sort du domaine tabulé."""
    try:
        (t0, t1), (d0, d1) = navire.hydro.bounds()
    except Exception:
        return 0.0
    return (max(0.0, t0 - eq.trim_m) + max(0.0, eq.trim_m - t1)
            + max(0.0, d0 - eq.draft_m) + max(0.0, eq.draft_m - d1))


# ------------------------------------------------------------------ recherche
def _depart(navire, cond, noms):
    """Remplissages de départ : ce qui est relevé aujourd'hui, 0 % sinon."""
    actuel = {t.capacite: t.fill_pc for t in cond.tanks}
    return {n: float(actuel.get(n, 0.0)) for n in noms}


def _densites_du_point(cond):
    """Les densités relevées au point, capacité par capacité.

    Une capacité absente du relevé n'y figure pas : elle suivra le dossier.
    Une capacité relevée sans densité propre non plus (`densite` à None) —
    c'est le même cas, et il ne faut pas le distinguer."""
    return {t.capacite: t.densite for t in cond.tanks
            if getattr(t, "densite", None) is not None}


def _descente(ev, etat, niveaux, journal=None, max_passes=40):
    """Descente de gradient discrète : à chaque passe, on essaie tous les
    niveaux de tous les ballasts et on garde le meilleur changement unique.
    On s'arrête dès qu'aucun changement n'améliore le score."""
    courant = etat
    for _ in range(max_passes):
        meilleur = courant
        for nom in courant.remplissages:
            for pc in niveaux:
                if pc == courant.remplissages[nom]:
                    continue
                essai = dict(courant.remplissages)
                essai[nom] = pc
                e = ev.etat(essai)
                if e.score < meilleur.score - 1e-9:
                    meilleur = e
        if meilleur is courant:
            break
        courant = meilleur
        if journal:
            journal(courant)
    return courant


def _descente_transfert(ev, etat, table, journal=None, max_passes=40):
    """Même principe, mais à volume d'eau constant : un mouvement consiste à
    prendre un volume dans un ballast et à le mettre dans un autre."""
    noms = list(etat.remplissages)
    fractions = (1.0, 0.5, 0.25, 0.1)
    courant = etat
    for _ in range(max_passes):
        meilleur = courant
        for a in noms:
            for b in noms:
                if a == b:
                    continue
                va = courant.remplissages[a]
                vb = courant.remplissages[b]
                if va <= 1e-9 or vb >= 100.0 - 1e-9:
                    continue                  # rien à prendre, ou rien à remplir
                vol_a = table.volume_max(a)
                vol_b = table.volume_max(b)
                if vol_a <= 0 or vol_b <= 0:
                    continue
                for f in fractions:
                    # on raisonne en m³ : deux ballasts n'ont pas le même volume
                    pris = f * va / 100.0 * vol_a
                    pris = min(pris, (100.0 - vb) / 100.0 * vol_b)
                    if pris <= 1e-6:
                        continue
                    essai = dict(courant.remplissages)
                    essai[a] = max(0.0, va - pris / vol_a * 100.0)
                    essai[b] = min(100.0, vb + pris / vol_b * 100.0)
                    e = ev.etat(essai)
                    if e.score < meilleur.score - 1e-9:
                        meilleur = e
        if meilleur is courant:
            break
        courant = meilleur
        if journal:
            journal(courant)
    return courant


def _affiner(ev, etat, table, transfert_seul, tours=2):
    """Réglage fin continu : la grille tombe rarement pile sur l'assiette
    visée. On reprend chaque ballast (ou chaque paire, en transfert) et on
    cherche par dichotomie le remplissage qui minimise le score."""
    courant = etat
    noms = list(etat.remplissages)
    for _ in range(tours):
        avant = courant.score
        if not transfert_seul:
            for nom in noms:
                base = dict(courant.remplissages)
                courant = _dichotomie(
                    ev, courant, lambda v, b=base, n=nom: {**b, n: v},
                    0.0, 100.0)
        else:
            for a in noms:
                for b in noms:
                    if a == b:
                        continue
                    base = dict(courant.remplissages)
                    va, vb = base[a], base[b]
                    vol_a, vol_b = table.volume_max(a), table.volume_max(b)
                    if vol_a <= 0 or vol_b <= 0:
                        continue
                    maxi = min(va / 100.0 * vol_a, (100.0 - vb) / 100.0 * vol_b)
                    if maxi <= 1e-6:
                        continue

                    def bouger(v, base=base, a=a, b=b, va=va, vb=vb,
                               vol_a=vol_a, vol_b=vol_b):
                        return {**base,
                                a: max(0.0, va - v / vol_a * 100.0),
                                b: min(100.0, vb + v / vol_b * 100.0)}

                    courant = _dichotomie(ev, courant, bouger, 0.0, maxi)
        if courant.score > avant - 1e-9:
            break
    return courant


def _nettoyer(ev, etat, table, transfert_seul=False, seuil_pc=2.0, seuil_m3=1.0):
    """Écarte les résidus de calcul.

    Un ballast laissé à 0,4 % n'est pas une manœuvre, c'est un artefact de la
    recherche — et il coûte pourtant tout le FSM de la capacité. On ramène ces
    quantités négligeables à vide ou à plein, puis on tente de sortir de
    carène liquide les ballasts restants, en ne gardant chaque changement que
    s'il ne dégrade pas la solution. En transfert seul, le volume total est
    conservé : le résidu est versé dans un autre ballast, jamais rejeté.
    """
    courant = etat
    for nom, pc in list(etat.remplissages.items()):
        vol = table.volume_max(nom)
        reste = min(pc, 100.0 - pc)
        if reste <= 0.0 or (reste > seuil_pc
                            and reste / 100.0 * vol > seuil_m3):
            continue
        cible = 0.0 if pc < 50.0 else 100.0
        essai = _poser(courant.remplissages, nom, cible, table, transfert_seul)
        if essai is None:
            continue
        e = ev.etat(essai)
        if e.score <= courant.score + 1e-9:
            courant = e

    for nom in sorted(courant.slack, key=lambda n: table.volume_max(n)):
        for cible in (0.0, 100.0):
            if courant.remplissages[nom] == cible:
                continue
            essai = _poser(courant.remplissages, nom, cible, table,
                           transfert_seul)
            if essai is None:
                continue
            e = ev.etat(essai)
            if e.score <= courant.score + 1e-9:
                courant = e
                break
    return courant


def _poser(remplissages, nom, cible, table, transfert_seul):
    """Met un ballast au niveau voulu. En transfert seul, la différence est
    prise ou versée dans les autres ballasts, du plus rempli au moins rempli,
    de sorte que le volume d'eau à bord ne change pas. Rend None si la place
    manque pour conserver le volume."""
    r = dict(remplissages)
    r[nom] = cible
    if not transfert_seul:
        return r
    reste = ((remplissages[nom] - cible) / 100.0) * table.volume_max(nom)
    autres = sorted((n for n in r if n != nom),
                    key=lambda n: -r[n] if reste > 0 else r[n])
    for n in autres:
        if abs(reste) < 1e-9:
            break
        vol = table.volume_max(n)
        if vol <= 0:
            continue
        libre = (100.0 - r[n]) / 100.0 * vol if reste > 0 else -r[n] / 100.0 * vol
        pris = reste if abs(reste) <= abs(libre) else libre
        r[n] += pris / vol * 100.0
        reste -= pris
    return None if abs(reste) > 1e-6 else r


def _dichotomie(ev, courant, construire, bas, haut, tours=18):
    """Recherche ternaire d'un minimum sur un paramètre continu. Le score n'est
    pas convexe en toute rigueur (l'entrée en carène liquide fait un saut) : on
    ne garde le résultat que s'il améliore réellement, jamais par principe."""
    meilleur = courant
    a, b = bas, haut
    for _ in range(tours):
        if b - a < 1e-4:
            break
        m1 = a + (b - a) / 3.0
        m2 = b - (b - a) / 3.0
        e1 = ev.etat(construire(m1))
        e2 = ev.etat(construire(m2))
        for e in (e1, e2):
            if e.score < meilleur.score - 1e-9:
                meilleur = e
        if e1.score <= e2.score:
            b = m2
        else:
            a = m1
    return meilleur


def resoudre(navire, cond, reglages):
    """Cherche la meilleure configuration de ballastage et rend un rapport
    comparant l'état de départ à l'état proposé."""
    # chrono de départ, nommé sans ambiguïté : plus bas, `t0` désignait la
    # borne basse d'assiette de la table — deux grandeurs sans rapport
    t_debut = time.perf_counter()
    rap = Rapport()
    noms = [n for n in reglages.tanks if n in navire.capacities]
    # une capacité sans table de jaugeage ne peut pas être remplie par
    # paliers : `_Table` échouerait (IndexError) — on l'écarte en le disant
    sans_jauge = [n for n in noms if not navire.capacity(n).jauge_rows]
    if sans_jauge:
        noms = [n for n in noms if n not in sans_jauge]
        rap.messages.append(
            "Sans table de jaugeage, donc hors recherche : "
            + ", ".join(sans_jauge) + ".")
    if not noms:
        rap.messages.append("Aucun ballast retenu : rien à chercher.")
        return rap
    if not getattr(navire, "a_pantocarenes", False):
        rap.messages.append(
            "Ce navire n'a pas de pantocarènes : la gîte indiquée est la "
            "gîte approchée des petits angles (tan θ = TCG / GM), pas la "
            "gîte d'équilibre exacte.")

    table = _Table(navire, noms, reglages.pas_pc, _densites_du_point(cond))
    ev = _Evaluateur(navire, cond, reglages, table)
    depart = ev.etat(_depart(navire, cond, noms), exact=True)
    rap.depart = depart

    debut = ev.etat(depart.remplissages)
    if reglages.transfert_seul:
        best = _descente_transfert(ev, debut, table)
    else:
        best = _descente(ev, debut, table.niveaux)
        # second départ, tous ballasts vides : la descente depuis l'état
        # courant peut rester coincée dans une configuration héritée
        vide = ev.etat({n: 0.0 for n in noms})
        autre = _descente(ev, vide, table.niveaux)
        if autre.score < best.score:
            best = autre
    if reglages.affiner:
        best = _affiner(ev, best, table, reglages.transfert_seul)
    best = _nettoyer(ev, best, table, reglages.transfert_seul)

    arrivee = ev.etat(best.remplissages, exact=True)
    rap.arrivee = arrivee
    rap.evaluations = ev.n
    rap.duree_s = time.perf_counter() - t_debut

    for nom in noms:
        av = table.ligne(nom, depart.remplissages[nom])[4]
        ap = table.ligne(nom, arrivee.remplissages[nom])[4]
        if abs(ap - av) > 1e-3:
            rap.operations.append((nom, av, ap))
    rap.operations.sort(key=lambda o: -abs(o[2] - o[1]))

    if not rap.operations:
        rap.messages.append(
            "Le ballastage actuel est déjà le meilleur des configurations "
            "essayées : aucune manœuvre proposée.")
    if arrivee.slack:
        # `_Table._ligne` suit la convention du dossier (navire.json /
        # « convention_fsm ») : annoncer le FSM maximal alors que le calcul a
        # compté le FSM réel faisait lire les chiffres à l'envers — le bord
        # croyait la solution plus conservative qu'elle ne l'est.
        compte = ("au FSM réel du remplissage" if table.fsm_reel
                  else "au FSM maximal")
        rap.messages.append(
            f"Ballasts laissés partiellement remplis (carène liquide comptée "
            f"{compte}) : " + ", ".join(sorted(arrivee.slack)) + ".")
    # Les volumes proposés se lisent en mètres cubes, mais ils pèsent : dire à
    # quelle densité, dès qu'elle n'est pas celle du dossier. Sans cela, le
    # bord lirait un déplacement qu'il ne saurait pas refaire.
    hors_dossier = sorted(
        f"{n} {table.densites[n]:.3f}".replace(".", ",")
        for n in noms
        if n in table.densites
        and abs(float(table.densites[n])
                - navire.capacity(n).density) > 5e-4)
    if hors_dossier:
        rap.messages.append(
            "Densité relevée au point, et non celle du dossier, pour : "
            + " ; ".join(hors_dossier) + " t/m³.")
    if not arrivee.dans_domaine:
        (t_min, t_max), (d_min, d_max) = navire.hydro.bounds()
        rap.messages.append(
            "La configuration proposée reste hors du domaine des tables "
            f"(assiette {t_min:+.2f} à {t_max:+.2f} m, tirant d'eau "
            f"{d_min:.2f} à {d_max:.2f} m) : le ballastage seul n'y ramène "
            "pas le navire. "
            "Aucun de ces chiffres n'a de valeur réglementaire — c'est la "
            "répartition des poids qu'il faut revoir.")
    elif reglages.assiette_cible_m is not None \
            and abs(arrivee.assiette_m - reglages.assiette_cible_m) > 0.05:
        (_t_min, _t_max), (_d_min, d_max) = navire.hydro.bounds()
        marge = d_max - arrivee.tirant_eau_m
        raison = (f" Le tirant d'eau n'est plus qu'à {marge:.2f} m du haut de "
                  "la table : embarquer davantage sortirait du domaine."
                  if marge < 0.25 else
                  " Les ballasts retenus n'ont pas le bras de levier qu'il "
                  "faudrait ; en ajouter d'autres, avant ou arrière, "
                  "élargirait la marge de manœuvre.")
        rap.messages.append(
            f"Assiette visée {reglages.assiette_cible_m:+.2f} m non atteinte "
            f"({arrivee.assiette_m:+.3f} m)." + raison)
    if reglages.transfert_seul:
        rap.messages.append(
            f"Transfert seul : {arrivee.eau_m3:.1f} m³ d'eau à bord, "
            "inchangé par construction.")
    return rap
