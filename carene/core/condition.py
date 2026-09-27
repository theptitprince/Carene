# -*- coding: utf-8 -*-
"""Modélisation d'une condition de chargement : lège + éléments de cargaison +
remplissage des capacités, agrégés en un poids total / centre de gravité. Ne
contient aucune donnée navire : les masses/centres viennent du Navire chargé
(lège, capacités) ou sont fournis par l'appelant (cargaison, saisie manuelle).
"""
from dataclasses import dataclass, field


@dataclass
class CargoItem:
    nom: str
    poids_t: float
    lcg_m: float
    tcg_m: float = 0.0
    vcg_m: float = 0.0
    # La cale d'où vient ce poids, s'il vient d'une cale (None : poids divers).
    # Le répartiteur en a besoin pour savoir ce qu'il redistribue et ce qui
    # reste en place : un nom qui « commence par Cale » ne le disait pas.
    code_cale: str = None


@dataclass
class TankState:
    capacite: str          # nom de la capacité dans navire.capacities
    fill_pc: float          # taux de remplissage, 0-100
    # Densité RELEVÉE AU POINT DE CHARGEMENT (t/m³), ou None pour celle du
    # dossier. Le dossier dit le produit prévu ; le point dit le produit
    # embarqué — eau de mer à 1,025 ou saumâtre, gazole à 0,84 ou à 0,87
    # selon la livraison. Voir `Capacity.avec_densite` : elle fait le poids ET
    # le moment de carène liquide, jamais les centres ni la sonde.
    densite: float = None

    def capacite_chargee(self, navire):
        """La capacité du dossier, relue à la densité de CE point.

        Porte unique : tout ce qui pèse cette capacité passe par elle, de
        sorte qu'aucun poids ni aucun FSM ne puisse être lu à une densité
        autre que celle qui est renseignée ici."""
        return navire.capacity(self.capacite).avec_densite(self.densite)


@dataclass
class Condition:
    navire: object
    cargo: list = field(default_factory=list)     # CargoItem
    tanks: list = field(default_factory=list)      # TankState
    inclure_lege: bool = True
    # id dans navire.json/profils_vent, ou None (résolu contre le navire —
    # aucun id de profil n'est codé ici : « CARGO » était un id du
    # navire de référence)
    profil_vent: str = None
    windage_area_m2: float = None                   # donnée "bateau x gréement", cf note ci-dessous
    windage_center_v_m: float = None
    lateral_plane_center_v_m: float = None

    def totals(self):
        """Retourne (poids_t, lcg_m, tcg_m, vcg_m, fsm_total_tm)."""
        w_total = lm_total = tm_total = vm_total = 0.0
        fsm_total = 0.0

        if self.inclure_lege:
            lege = self.navire.lege
            # TCG facultatif : souvent omis des dossiers (≈ 0 pour un navire
            # à moteur symétrique) — l'absence ne doit pas faire échouer
            w, lcg, tcg, vcg = (lege["masse_t"], lege["lcg_m"],
                                 lege.get("tcg_m", 0.0), lege["vcg_m"])
            w_total += w
            lm_total += w * lcg
            tm_total += w * tcg
            vm_total += w * vcg

        for item in self.cargo:
            w_total += item.poids_t
            lm_total += item.poids_t * item.lcg_m
            tm_total += item.poids_t * item.tcg_m
            vm_total += item.poids_t * item.vcg_m

        for ts in self.tanks:
            # Densité du POINT quand elle est renseignée, celle du dossier
            # sinon : poids et FSM (tabulé comme maximal) sont lus à l'échelle
            # par la même porte, donc toujours cohérents entre eux.
            cap = ts.capacite_chargee(self.navire)
            row = cap.at_fill_pc(ts.fill_pc)
            w = row["Poids_t"]
            w_total += w
            lm_total += w * row["LCG_m"]
            tm_total += w * row.get("TCG_m", 0.0)
            # VCG **solide**, jamais VCG_corrige_m : dans les tables de
            # jaugeage du dossier, VCG_corrige = VCG + FSM/Poids — la carène
            # liquide y est déjà incluse. La compter ici *et* dans
            # `stability.kg_effectif` la comptait deux fois (jusqu'à 0,46 m de
            # KG sur le navire de référence, toutes capacités à moitié
            # pleines, soit un GM
            # corrigé faux de la même quantité, et des verdicts inversés).
            # La correction est portée une seule fois, par `fsm_total`.
            vm_total += w * row.get("VCG_m", 0.0)
            if 0.0 < ts.fill_pc < 100.0:
                # La convention de carène liquide appartient au DOSSIER du
                # navire, pas au code (navire.json / « convention_fsm ») :
                # - « max » (défaut faute de déclaration) : FSM maximal de la
                #   capacité dès qu'elle est slack — conservative ;
                # - « reel » : FSM interpolé au remplissage courant, pratique
                #   IMO courante, et celle du dossier de référence (D-14).
                if getattr(self.navire, "convention_fsm", "max") == "reel":
                    fsm_total += float(row.get("FSM_tm", cap.fsm_max_tm))
                else:
                    fsm_total += cap.fsm_max_tm

        if w_total <= 0:
            return 0.0, 0.0, 0.0, 0.0, 0.0
        return (w_total, lm_total / w_total, tm_total / w_total,
                vm_total / w_total, fsm_total)

    # ------------------------------------------------------ surface au vent
    def surface_au_vent(self, te_milieu_m):
        """(id de configuration, dict des cinq grandeurs, note) au tirant
        d'eau d'équilibre — ou (None, None, motif) si le navire ne décrit
        aucune configuration de voilure.

        Les valeurs passées à la main (`windage_area_m2`…) restent
        prioritaires : un appelant qui les fournit sait ce qu'il fait (c'est
        ainsi que `tools/valider_reference.py` rejoue les cas du dossier), et
        elles ne portent pas de note puisqu'elles ne sont pas interpolées."""
        if self.windage_area_m2 is not None:
            return (self.profil_vent, {
                "Windage_area_m2": self.windage_area_m2,
                "Windage_V_m": self.windage_center_v_m,
                "Lateral_plane_area_m2": None,
                "Lateral_plane_V_m": self.lateral_plane_center_v_m,
                "Z_windage_lateral_m": (
                    None if self.windage_center_v_m is None
                    or self.lateral_plane_center_v_m is None
                    else self.windage_center_v_m
                    - self.lateral_plane_center_v_m)}, "")
        profils = getattr(self.navire, "profils_vent", None)
        if not profils:
            return None, None, ("le dossier de ce navire ne décrit aucune "
                                "configuration de voilure")
        pid = profils.resoudre(self.profil_vent)
        if pid is None:
            return None, None, ("le dossier de ce navire ne décrit aucune "
                                "configuration de voilure")
        vent, note = profils.surface_au_vent(pid, te_milieu_m)
        return pid, vent, note


# Note windage : l'aire et le centre de la surface exposée au vent dépendent du
# profil hors-l'eau du navire ET du gréement déployé (voilure complète /
# intermédiaire / réduite / cargo) — c'est une donnée "bateau x gréement", pas
# une formule universelle du critère météo. Tant que ce profil n'est pas
# numérisé (futur ajout à l'utilitaire Carène : silhouette calée comme les
# plans de pont), elle est fournie en entrée de la condition (windage_area_m2,
# windage_center_v_m, lateral_plane_center_v_m) plutôt que recalculée par le
# moteur — voir navires/<NOM>/validation/cas_vent.csv pour les 15 cas
# officiels du dossier de stabilité, utilisés tels quels en validation.
