# -*- coding: utf-8 -*-
"""Chargement du dossier "navire virtuel" (navires/<NOM>/). Ce module lit des
fichiers CSV/JSON génériques : il ne connaît aucune valeur numérique propre à un
navire particulier, seulement le FORMAT du dossier (voir tools/build_navire_*.py
et le fichier navire.json de chaque navire pour la documentation du format).
"""
import csv
import json
import os

import numpy as np

from .interp import Grid2D

# Colonne d'une table de jaugeage absente : un tableau vide plutôt qu'une
# erreur, comme le faisait la liste en compréhension d'avant.
_COLONNE_VIDE = np.empty(0, dtype=float)


def _est_numerique(v):
    """Un nombre FINI : « nan » et « inf » se lisent comme des flottants mais
    ne sont pas des valeurs de table — les accepter les faisait entrer dans
    les interpolations sans un mot (D-82)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return False
    return x == x and x not in (float("inf"), float("-inf"))


def _read_csv_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _grid2d_from_rows(rows, axis1_key, axis2_key, value_keys, incompletes=None):
    """Grille 2D depuis les lignes d'un CSV.

    Une colonne FACULTATIVE (LCF, TPC…) peut être vide sur certaines lignes :
    la fenêtre « Création du navire » écrit "" là où le fichier importé
    n'avait rien. Une telle colonne est écartée de la grille plutôt que de
    faire échouer tout le chargement (float("") -> ValueError) ou d'inventer
    une valeur ; son nom est ajouté à `incompletes` si une liste est fournie.
    Les colonnes obligatoires (déplacement, LCB, KMt…) sont toujours
    complètes : l'import refuse une ligne où elles manquent.
    """
    by_axis1 = {}
    for r in rows:
        a1 = round(float(r[axis1_key]), 6)
        by_axis1.setdefault(a1, []).append(r)
    axis1_values = sorted(by_axis1.keys())
    keys = []
    for k in value_keys:
        if all(_est_numerique(r.get(k)) for r in rows):
            keys.append(k)
        elif incompletes is not None:
            incompletes.append(k)
    rows_axis2, rows_values = [], []
    for a1 in axis1_values:
        rs = sorted(by_axis1[a1], key=lambda r: float(r[axis2_key]))
        rows_axis2.append([float(r[axis2_key]) for r in rs])
        rows_values.append({k: [float(r[k]) for r in rs] for k in keys})
    return Grid2D(axis1_values, rows_axis2, rows_values)


class Capacity:
    """Une capacité (soute, ballast, cale...) : caractéristiques statiques
    (capacites.csv) + table de jaugeage (jauges/<NOM>.csv)."""

    def __init__(self, name, meta, jauge_rows):
        self.name = name
        self.meta = meta  # dict issu de capacites.csv (densité, volume, FSM max, ...)
        # np.interp exige des abscisses croissantes : une table de jaugeage
        # saisie ou exportée dans le désordre (100 % en tête, par exemple)
        # donnerait des interpolations fausses sans lever d'erreur. On trie
        # donc ici, une fois pour toutes, par remplissage croissant.
        self.jauge_rows = sorted(
            jauge_rows,
            key=lambda r: float(r.get("Remplissage_pc", 0.0) or 0.0))
        # Colonnes numériques sur TOUTES les lignes : une colonne facultative
        # (sondage, creux…) partiellement vide est écartée plutôt qu'inventée
        # ou que de faire échouer l'interpolation par float("").
        self.colonnes = [k for k in (self.jauge_rows[0].keys() if self.jauge_rows else [])
                         if all(_est_numerique(r.get(k)) for r in self.jauge_rows)]
        # Les colonnes sont figées une fois pour toutes, en numpy : `_col` les
        # rebâtissait à chaque appel, et `at_fill_pc` en demande une par
        # colonne — soit, pour une soute à cent lignes de jaugeage, une dizaine
        # de listes reconstruites à chaque lecture, et un import de numpy dans
        # la boucle. Les tableaux sont PARTAGÉS : personne ne les écrit.
        self._colonnes_np = {
            k: np.array([float(r[k]) for r in self.jauge_rows], dtype=float)
            for k in self.colonnes}

    def _meta_float(self, key, defaut=0.0):
        """Lecture numérique tolérante d'une colonne de capacites.csv.

        Une cellule vide (colonne facultative non renseignée dans l'éditeur
        de navire) faisait lever float("") -> ValueError ; elle vaut ici le
        défaut, comme une colonne absente."""
        v = self.meta.get(key)
        if v is None:
            return float(defaut)
        s = str(v).strip()
        if s == "":
            return float(defaut)
        try:
            return float(s.replace(",", "."))
        except ValueError:
            return float(defaut)

    @property
    def volume_max_m3(self):
        return self._meta_float("Volume_net_m3", 0.0)

    @property
    def density(self):
        return self._meta_float("Densite", 1.0)

    @property
    def fsm_max_tm(self):
        """Le moment de carène liquide maximal de la capacité (t·m).

        La colonne `FSM_max_tm` de capacites.csv n'est que « recommandée » :
        absente, elle valait 0 — et en convention « max », celle qui
        s'applique par défaut et se dit la plus prudente, TOUTE la carène
        liquide disparaissait (674,7 t·m, 0,33 m de GM, sur une copie
        du navire de référence sans la colonne). On prend alors le plus grand FSM de la
        table de jaugeage ; sans l'un ni l'autre, 0 — et `fsm_inconnu` le
        dit, pour que le navire le signale."""
        brut = self.meta.get("FSM_max_tm")
        if brut is not None and str(brut).strip() != "":
            return self._meta_float("FSM_max_tm", 0.0)
        col = self._col("FSM_tm")
        return float(col.max()) if len(col) else 0.0

    @property
    def fsm_inconnu(self):
        """Ni FSM maximal au dossier, ni colonne FSM dans la jauge."""
        brut = self.meta.get("FSM_max_tm")
        return ((brut is None or str(brut).strip() == "")
                and not len(self._col("FSM_tm")))

    def _col(self, name):
        """La colonne, telle qu'elle a été figée au chargement (tableau numpy
        partagé, à ne pas modifier en place). Une table de jaugeage absente ne
        donne aucune colonne : on rend un tableau vide, pas une erreur."""
        return self._colonnes_np.get(name, _COLONNE_VIDE)

    def at_fill_pc(self, fill_pc):
        """Interpole la ligne de jaugeage à un taux de remplissage (%) donné."""
        fills = self._col("Remplissage_pc")
        out = {}
        for key in self.colonnes:
            if key == "Remplissage_pc":
                continue
            out[key] = float(np.interp(fill_pc, fills, self._col(key)))
        out["Remplissage_pc"] = fill_pc
        return out

    def _interp_par(self, colonne, valeur):
        """Ligne de jaugeage interpolée en entrant par `colonne`.

        La colonne d'entrée doit croître avec le remplissage (c'est le cas du
        sondage, du volume et du poids). On borne à l'intervalle tabulé plutôt
        que d'extrapoler : une sonde plus haute que la capacité n'a pas de sens.
        """
        if not self.jauge_rows or colonne not in self.colonnes:
            raise KeyError(f"colonne « {colonne} » absente de la table de jaugeage")
        xs = self._col(colonne)
        fills = self._col("Remplissage_pc")
        ordre = np.argsort(xs)
        xs = xs[ordre]
        fills = fills[ordre]
        v = min(max(float(valeur), float(xs[0])), float(xs[-1]))
        return self.at_fill_pc(float(np.interp(v, xs, fills)))

    def at_sounding(self, sondage_m):
        """Ligne de jaugeage à une hauteur de sonde relevée (m)."""
        return self._interp_par("Sondage_m", sondage_m)

    def at_volume(self, volume_m3):
        """Ligne de jaugeage à un volume connu (m³)."""
        return self._interp_par("Volume_m3", volume_m3)

    def plage(self, colonne):
        """(min, max) tabulés d'une colonne — pour borner une saisie."""
        if not self.jauge_rows or colonne not in self.colonnes:
            return (0.0, 0.0)
        vals = self._col(colonne)
        return (float(vals.min()), float(vals.max()))

    @property
    def a_sondage(self):
        return bool(self.jauge_rows) and "Sondage_m" in self.colonnes

    def at_weight(self, weight_t):
        """Interpole la ligne de jaugeage au poids (t) donné (recherche par
        poids plutôt que par remplissage — utile en saisie directe de masse).

        Passe par `_interp_par`, comme la sonde et le volume : la version
        recopiée ici ne triait pas la colonne d'entrée et ne bornait pas la
        valeur, de sorte qu'une table exportée dans le désordre ou une masse
        au-delà du plein rendaient un remplissage faux, sans rien signaler."""
        return self._interp_par("Poids_t", weight_t)

    @property
    def densite_dossier(self):
        """La densité écrite au dossier (`capacites.csv`, colonne Densite).

        Même valeur que `density` sur la capacité du dossier ; sur une
        capacité relue à la densité d'un point de chargement
        (`avec_densite`), `density` est celle du point et celle-ci reste
        celle du dossier. Les deux se lisent donc de la même manière partout,
        sans avoir à savoir laquelle des deux on tient."""
        return self.density

    def avec_densite(self, densite):
        """La MÊME capacité, lue à la densité du POINT DE CHARGEMENT.

        Pourquoi : la densité du dossier est celle du produit prévu, pas celle
        de la livraison. Le bord embarque de l'eau de mer à 1,025 ou de l'eau
        saumâtre, du gazole à 0,84 ou à 0,87 selon le fournisseur. Il faut
        pouvoir peser ce qui est réellement dans la capacité sans toucher au
        dossier du navire, qui est une donnée du chantier.

        Ce que la densité change, et ce qu'elle ne change pas — c'est TOUTE la
        physique de cette porte, et il n'y en a pas d'autre :

        - la **géométrie** ne bouge pas. À un remplissage donné, le liquide
          occupe le même volume, monte à la même sonde, et son centre
          (LCG, TCG, VCG) est au même endroit : changer de produit ne déplace
          aucune paroi ;
        - le **poids** est ρ × V : il suit la densité, donc
          `Poids_t = Poids_t_dossier × ρ'/ρ` ;
        - le **moment de carène liquide** suit la densité LUI AUSSI, et c'est
          le point qu'on oublie : FSM = ρ × i, où `i` est le moment d'inertie
          de la surface libre — une grandeur purement géométrique (m⁴). La
          table du dossier tabule déjà ρ × i ; la remettre à l'échelle ρ'/ρ
          est donc exact, et `fsm_max_tm` se remet à l'échelle de même. Un
          gazole plus léger fait une carène liquide plus faible, pas égale ;
        - le **VCG corrigé** (VCG + FSM/Poids) est par conséquent
          **invariant** : le rapport FSM/Poids vaut i/V, qui ne dépend pas de
          la densité. La colonne `VCG_corrige_m` du dossier reste juste telle
          quelle.

        `densite` à None, ou égale à celle du dossier, rend la capacité
        elle-même : sans densité saisie, aucun chiffre ne change, pas même au
        dernier décimal, et aucun objet n'est fabriqué.

        Une densité ≤ 0 ou absurde est refusée À LA SAISIE, pas ici : le
        moteur calcule ce qu'on lui donne, et c'est l'interface qui garde la
        porte (voir `tanks_table.TanksTable._on_edit`)."""
        if densite is None:
            return self
        d = float(densite)
        if abs(d - self.density) <= 1e-12:
            return self
        return _CapaciteADensite(self, d)


class _CapaciteADensite:
    """Une capacité du dossier, relue à la densité d'un point de chargement.

    Tout ce qui n'est pas pondéral est délégué tel quel à la capacité du
    dossier (nom, table de jaugeage, volume net, colonnes, `a_sondage`…) : il
    n'y a **qu'une** table de jaugeage, celle du dossier. Seules les deux
    colonnes qui portent la densité — poids et moment de carène liquide — sont
    remises à l'échelle, et toujours par le même rapport. Voir
    `Capacity.avec_densite` pour le pourquoi.

    Cette classe se substitue à une `Capacity` partout où le code en tient
    une : c'est ce qui permet à chaque consommateur (bilan, rapports,
    ballastage, tableau des capacités) de voir la densité du point sans rien
    changer à sa lecture des lignes de jauge.
    """

    # Les colonnes de jauge qui valent « géométrie × densité » : ce sont les
    # seules à suivre le produit embarqué.
    PONDERALES = ("Poids_t", "FSM_tm")

    def __init__(self, base, densite):
        self._base = base
        self._densite = float(densite)

    def __getattr__(self, nom):
        # Filet de sécurité : sans cette garde, un attribut spécial demandé
        # avant que `_base` existe (copie, pickle) relancerait __getattr__ sur
        # lui-même à l'infini.
        if nom in ("_base", "_densite"):
            raise AttributeError(nom)
        return getattr(self._base, nom)

    def __repr__(self):
        return (f"<capacité {self._base.name} à densité {self._densite:g} "
                f"(dossier : {self._base.density:g})>")

    # ------------------------------------------------------------- densité
    @property
    def density(self):
        """La densité EMPLOYÉE : celle du point."""
        return self._densite

    @property
    def densite_dossier(self):
        return self._base.density

    @property
    def rapport_densite(self):
        """ρ'/ρ : le facteur unique de toutes les grandeurs pondérales.

        Un dossier qui déclarerait une densité nulle ne permet aucune mise à
        l'échelle (il n'y a rien à mettre à l'échelle : ses poids tabulés sont
        nuls) : on rend 1, ce qui laisse la table telle quelle."""
        d0 = self._base.density
        return self._densite / d0 if d0 else 1.0

    def avec_densite(self, densite):
        """Une autre densité repart TOUJOURS du dossier : les vues ne
        s'empilent pas, et le rapport reste ρ'/ρ, jamais ρ''/ρ'."""
        return self._base.avec_densite(densite)

    # --------------------------------------------------- lignes de jaugeage
    def _echelle(self, ligne):
        k = self.rapport_densite
        if k == 1.0:
            return ligne
        out = dict(ligne)
        for cle in self.PONDERALES:
            if cle in out:
                out[cle] = float(out[cle]) * k
        return out

    def at_fill_pc(self, fill_pc):
        return self._echelle(self._base.at_fill_pc(fill_pc))

    def at_sounding(self, sondage_m):
        return self._echelle(self._base.at_sounding(sondage_m))

    def at_volume(self, volume_m3):
        return self._echelle(self._base.at_volume(volume_m3))

    def at_weight(self, weight_t):
        """Entrée par le poids AU SENS DE LA DENSITÉ DU POINT.

        Le bord tape « 12 t de gazole » : ce sont 12 t du produit qu'il a
        embarqué. La table, elle, n'indexe que des poids du dossier — on
        reconvertit donc avant d'interpoler, sans quoi une soute renseignée en
        masse se serait remplie au mauvais niveau dès que la densité diffère."""
        k = self.rapport_densite
        return self._echelle(self._base.at_weight(float(weight_t) / k if k else 0.0))

    def plage(self, colonne):
        lo, hi = self._base.plage(colonne)
        if colonne in self.PONDERALES:
            k = self.rapport_densite
            return (lo * k, hi * k)
        return (lo, hi)

    # ----------------------------------------------------------- agrégats
    @property
    def fsm_max_tm(self):
        """Le FSM maximal suit la densité comme le FSM tabulé : c'est le même
        ρ × i, pris au remplissage le plus défavorable."""
        return self._base.fsm_max_tm * self.rapport_densite


class Navire:
    """Représentation en mémoire d'un navire virtuel chargé depuis son dossier.
    Aucune valeur n'est codée en dur ici : tout vient des fichiers du dossier."""

    def __init__(self, path):
        self.path = path
        with open(os.path.join(path, "navire.json"), encoding="utf-8") as f:
            self.manifest = json.load(f)

        # avertissements de chargement (colonnes facultatives incomplètes…),
        # à afficher par l'interface : rien n'est perdu en silence
        self.messages = []
        # `convention_fsm` est relue à chaque capacité slack : sans ce drapeau,
        # le même avertissement s'empilerait des milliers de fois pendant une
        # recherche de ballastage
        self._fsm_signalee = False
        hydro_rows = _read_csv_rows(os.path.join(path, "hydrostatiques.csv"))
        hydro_cols = [c for c in hydro_rows[0].keys() if c not in ("Assiette_m", "TE_milieu_m")]
        incompletes = []
        self.hydro = _grid2d_from_rows(hydro_rows, "Assiette_m", "TE_milieu_m",
                                       hydro_cols, incompletes)
        if incompletes:
            self.messages.append(
                "hydrostatiques.csv : colonne(s) incomplète(s) ignorée(s) : "
                + ", ".join(incompletes))

        # Pantocarènes : facultatives au chargement — un dossier en cours de
        # constitution (hydro seule) doit déjà permettre équilibre et tirants
        # d'eau. Sans elles, gz_curve lèvera une erreur explicite.
        kn_path = os.path.join(path, "pantocarenes_kn.csv")
        self.kn = None
        self.kn_heel_angles = []
        self._kn_colonnes = {}       # angle (float) -> nom de colonne exact
        # tables (gîtes, KN) déjà interpolées, voir kn_at
        self._kn_memo = {}
        if os.path.exists(kn_path):
            kn_rows = _read_csv_rows(kn_path)
            kn_cols = [c for c in kn_rows[0].keys()
                       if c not in ("Assiette_m", "Deplacement_t")]
            kn_incompletes = []
            self.kn = _grid2d_from_rows(kn_rows, "Assiette_m",
                                        "Deplacement_t", kn_cols, kn_incompletes)
            if kn_incompletes:
                # une colonne à trous est écartée de la grille : elle doit
                # l'être aussi des angles, sinon `kn_at` la demande et tombe
                # sur un KeyError incompréhensible (D-82)
                self.messages.append(
                    "pantocarenes_kn.csv : angle(s) sans valeur à certaines "
                    "assiettes, ignoré(s) : " + ", ".join(kn_incompletes))
                kn_cols = [c for c in kn_cols if c not in kn_incompletes]
            # le nom de colonne est mémorisé tel quel : le reconstruire par
            # f"KN_{int(angle)}" tronquait les angles décimaux (KN_7.5 -> KN_7)
            for c in kn_cols:
                if c.startswith("KN_"):
                    try:
                        self._kn_colonnes[float(c[3:])] = c
                    except ValueError:
                        continue
            self.kn_heel_angles = sorted(self._kn_colonnes)

        kgmax_path = os.path.join(path, "kgmax_gmmin.csv")
        self.kgmax = None
        self.kgmax_lignes = []
        if os.path.exists(kgmax_path):
            kgmax_rows = _read_csv_rows(kgmax_path)
            # toute colonne non numérique est ignorée génériquement : le nom
            # « Critere_limitant » n'est qu'une convention du dossier de référence
            kgmax_cols = [c for c in kgmax_rows[0].keys()
                          if c not in ("Assiette_m", "Deplacement_t")
                          and _est_numerique(kgmax_rows[0][c])]
            self.kgmax = _grid2d_from_rows(kgmax_rows, "Assiette_m", "Deplacement_t", kgmax_cols)
            # les lignes telles quelles : la grille ne garde que le numérique,
            # or le dossier écrit À CÔTÉ de chaque KG max le critère qui le
            # limite (« a' Area < 'b' Area »). C'est un renseignement, pas un
            # calcul : le rapport le cite tel quel (D-59), sans l'interpoler.
            self.kgmax_lignes = kgmax_rows

        # Un navire sans capacité liquide déclarée reste calculable (équilibre
        # et courbe GZ ne dépendent que des tables de carène) : capacites.csv
        # est donc facultatif, comme kgmax_gmmin.csv et points_envahissement.csv.
        cap_path = os.path.join(path, "capacites.csv")
        cap_rows = _read_csv_rows(cap_path) if os.path.exists(cap_path) else []
        jauge_dir = os.path.join(path, "jauges")
        self.capacities = {}
        for r in cap_rows:
            name = r["Nom"]
            fn = name.replace(" ", "_").replace("/", "_") + ".csv"
            jp = os.path.join(jauge_dir, fn)
            jauge_rows = _read_csv_rows(jp) if os.path.exists(jp) else []
            self.capacities[name] = Capacity(name, r, jauge_rows)
            if self.capacities[name].fsm_inconnu:
                # ni FSM maximal, ni colonne FSM dans la jauge : la carène
                # liquide de cette capacité sera comptée NULLE — on le dit
                self.messages.append(
                    f"Capacité « {name} » : aucun moment de carène liquide "
                    "au dossier (ni FSM_max_tm, ni colonne FSM_tm dans sa "
                    "jauge) — sa carène liquide est comptée nulle.")

        pts_path = os.path.join(path, "points_envahissement.csv")
        self.points_envahissement = _read_csv_rows(pts_path) if os.path.exists(pts_path) else []

        # Configurations de voilure et surfaces au vent (profils_vent.csv +
        # navire.json › profils_vent) : facultatives comme le reste. None =
        # le dossier n'en décrit pas, et le logiciel se comporte exactement
        # comme avant leur existence — pas un critère de plus, pas un message.
        from .voilure import ProfilsVent
        self.profils_vent = ProfilsVent.charger(path, self.manifest)
        if self.profils_vent is not None:
            self.messages.extend(self.profils_vent.messages)

    @classmethod
    def load(cls, path):
        return cls(path)

    @property
    def lege(self):
        return self.manifest["lege"]

    @property
    def criteres(self):
        # section facultative : tous les seuils ont des défauts IMO en code,
        # et un dossier fait main peut très bien ne pas la fournir
        return self.manifest.get("criteres", {})

    @property
    def convention_fsm(self):
        """« max » (défaut, conservative) : dès qu'une capacité est en carène
        liquide, on compte son FSM maximal.
        « reel » : on compte le FSM interpolé au remplissage courant, pratique
        IMO courante — et **la convention du dossier de référence**, dont le recueil
        approuvé et le recueil d'épreuve LOCOPIAS comptent tous deux au
        remplissage réel (D-14). Se déclare dans navire.json
        (« convention_fsm »).

        Un dossier qui ne la déclare pas, ou qui l'écrit autrement que dans ces
        deux mots (« moyen », « maximum »… ; « réel » accentué et les
        majuscules sont reconnus depuis D-76), reçoit le défaut « max » — mais
        jamais en silence : retomber sur une convention plus conservative que
        celle du recueil change les FSM, donc le GM corrigé, donc les verdicts.
        L'avertissement est empilé une seule fois, à la première lecture."""
        brut = self.manifest.get("convention_fsm")
        v = str(brut).strip().lower() if brut is not None else ""
        # « réel » accentué est la façon naturelle de l'écrire en français :
        # le refuser faisait retomber sur « max » un dossier qui disait bien
        # « réel » (2.20.1)
        v = v.replace("é", "e").replace("è", "e")
        if v in ("max", "reel"):
            return v
        if not self._fsm_signalee:
            self._fsm_signalee = True
            quoi = ("non déclarée" if brut is None or v == ""
                    else f"non reconnue (« {brut} »)")
            self.messages.append(
                f"navire.json : convention de carène liquide {quoi} : "
                "« max » appliquée par défaut.")
        return "max"

    def hydro_at(self, trim_m, draft_m, method="linear"):
        return self.hydro.row_at(trim_m, draft_m, method)

    def kn_at(self, trim_m, displacement_t, heel_deg, method="pchip"):
        """KN interpolé à (assiette, déplacement, gîte). Le domaine de gîte
        couvert par la table est [0, max(kn_heel_angles)] (voir navire.json /
        pantocarenes_kn.csv) ; au-delà, la valeur est prolongée linéairement à
        partir des deux derniers points, ce qui devient rapidement peu fiable.

        Le domaine en **assiette et déplacement** est celui de la table des
        pantocarènes, qui n'est pas le même que celui de la table
        hydrostatique : voir `domaine_kn`. Cette méthode ne le vérifie pas —
        c'est `gz_curve` qui le fait et l'inscrit dans son résultat."""
        if self.kn is None:
            raise ValueError(
                "Ce navire n'a pas de table de pantocarènes (KN) : la courbe "
                "GZ ne peut pas être calculée. Importez-la dans « Créer ou "
                "modifier le navire… ».")
        # La table (gîtes, KN) ne dépend QUE de (assiette, déplacement) : une
        # courbe GZ la redemandait à chaque degré de gîte, soit neuf
        # interpolations de grille par point pour un résultat identique. On la
        # garde donc, indexée sur ces deux valeurs arrondies au milliardième
        # (les mêmes flottants reviennent tels quels d'un angle à l'autre) et
        # sur l'identité de la table du dossier — un navire rechargé recalcule.
        cle = (round(float(trim_m), 9), round(float(displacement_t), 9),
               id(self.kn), len(self.kn_heel_angles))
        memo = self._kn_memo.get(cle)
        if memo is None:
            # une table importée avec une colonne « KN 0 » ferait doublon avec
            # le zéro ajouté ici : PCHIP rendrait des NaN sans lever d'erreur
            heels, kns = [0.0], [0.0]
            for h in self.kn_heel_angles:
                if abs(float(h)) < 1e-9:
                    continue
                heels.append(float(h))
                # nom de colonne mémorisé au chargement : les angles décimaux
                # (7.5°…) sont courants dans les dossiers réels
                col = self._kn_colonnes.get(float(h), f"KN_{h:g}")
                kns.append(self.kn.value(trim_m, displacement_t, col,
                                         method="linear"))
            memo = (heels, kns)
            # borné : une recherche de ballastage essaie des milliers de
            # configurations, et un cache sans plafond serait une fuite. Les
            # 64 dernières clés suffisent — une courbe GZ n'en use qu'une.
            if len(self._kn_memo) >= 64:
                self._kn_memo.pop(next(iter(self._kn_memo)))
            self._kn_memo[cle] = memo
        heels, kns = memo
        from .interp import pchip_eval, interp1d_linear
        signe = 1 if heel_deg >= 0 else -1
        if method == "pchip":
            return pchip_eval(heels, kns, abs(heel_deg)) * signe
        return interp1d_linear(heels, kns, abs(heel_deg)) * signe

    def domaine_kn(self, trim_m, displacement_t):
        """La table des pantocarènes couvre-t-elle ce point ?

        Les deux tables du dossier n'ont pas les mêmes bornes — sur le
        navire de référence,
        hydrostatiques 1129→2689 t mais pantocarènes 1300→2700 t. Un équilibre
        peut donc être parfaitement dans le domaine hydrostatique alors que la
        courbe GZ, elle, repose sur des KN écrêtés en bord de table."""
        if self.kn is None:
            return False
        try:
            return self.kn.contains(trim_m, displacement_t)
        except Exception:
            # Une table inexploitable ne « couvre » rien : répondre True
            # faisait présenter des KN extrapolés comme s'ils étaient tabulés.
            return False

    def bornes_kn(self, trim_m=None):
        if self.kn is None:
            return (0.0, 0.0), (0.0, 0.0)
        return self.kn.bounds(trim_m)

    @property
    def a_pantocarenes(self):
        return self.kn is not None and bool(self.kn_heel_angles)

    def capacity(self, name):
        return self.capacities[name]

    def est_capacite(self, nom):
        """Ce nom désigne-t-il une capacité liquide du dossier ?

        Sert à trier ce qui est tracé sur un plan : sur le même pont, un
        dessinateur trace aussi bien les cales que les soutes. Le dossier fait
        foi — une forme dont le nom est dans `capacites.csv` est une capacité
        liquide, les autres sont des cales. Aucun nom n'est codé en dur."""
        if not nom:
            return False
        if nom in self.capacities:
            return True
        cible = str(nom).strip().casefold()
        return any(str(k).strip().casefold() == cible for k in self.capacities)
