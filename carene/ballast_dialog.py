# -*- coding: utf-8 -*-
"""Solutionneur de ballastage : réglages, exécution, compte rendu.

On choisit les ballasts sur lesquels on accepte de jouer et ce qu'on s'autorise
à faire — embarquer et rejeter, ou seulement transférer d'une capacité à
l'autre. Le solveur cherche la meilleure répartition et rend un **avant /
après** chiffré, plus la liste des manœuvres. Rien n'est appliqué tant qu'on
n'a pas cliqué « Appliquer ».
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .bilan import densite_texte
from .condition_model import VOLUME, TankFill
from .core import ballast
from .saisie import SpinNombre


class BallastDialog(QDialog):
    """Règle et lance le solutionneur de ballastage, puis rend compte."""

    def __init__(self, win, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.rapport = None
        self.setWindowTitle("Ballastage")
        self.resize(760, 780)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        titre = QLabel("Solutionneur de ballastage")
        titre.setStyleSheet("font-size: 18px; font-weight: bold;")
        root.addWidget(titre)
        intro = QLabel(
            "Cherche la meilleure répartition dans les ballasts retenus. Dans "
            "l'ordre : tenir la gîte visée (nulle, sauf à en vouloir une), "
            "tenir l'assiette visée, garder le "
            "meilleur GM corrigé, embarquer le moins d'eau. Les ballasts "
            "laissés partiellement remplis sont évités — ils coûtent tout leur "
            "FSM — mais autorisés si la cible l'exige.")
        intro.setObjectName("hint")
        intro.setWordWrap(True)
        root.addWidget(intro)

        root.addWidget(self._carte_reglages())
        root.addWidget(self._carte_ballasts())

        self.zone = QScrollArea()
        self.zone.setWidgetResizable(True)
        self.zone.setFrameShape(QFrame.Shape.NoFrame)
        self.zone.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        self.compte = QVBoxLayout(inner)
        self.compte.setContentsMargins(0, 0, 0, 0)
        self.compte.setSpacing(5)
        self.zone.setWidget(inner)
        root.addWidget(self.zone, 1)

        row = QHBoxLayout()
        self.btn_run = QPushButton("Chercher")
        self.btn_run.setProperty("accent", "1")
        self.btn_run.clicked.connect(self.run)
        self.btn_apply = QPushButton("Appliquer ce ballastage")
        self.btn_apply.setProperty("accent", "1")
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self.accept)
        b_close = QPushButton("Fermer")
        b_close.clicked.connect(self.reject)
        row.addWidget(self.btn_run)
        row.addStretch(1)
        row.addWidget(b_close)
        row.addWidget(self.btn_apply)
        root.addLayout(row)

        self._dire("Choisissez les ballasts, puis cliquez « Chercher ».", "hint")

    # ------------------------------------------------------------- réglages
    def _carte_reglages(self):
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 14)
        t = QLabel("Ce qu'on s'autorise")
        t.setObjectName("cardTitle")
        lay.addWidget(t)

        self.rb_libre = QRadioButton(
            "Ballaster et déballaster librement (prise et rejet à la mer)")
        self.rb_libre.setChecked(True)
        self.rb_transfert = QRadioButton(
            "Transfert seul : le volume d'eau à bord ne change pas")
        self.rb_transfert.setToolTip(
            "Utile en eaux où le rejet est interdit, ou quand on veut garder "
            "son port en lourd : le solveur ne fait que déplacer l'eau déjà "
            "embarquée d'un ballast à l'autre.")
        lay.addWidget(self.rb_libre)
        lay.addWidget(self.rb_transfert)

        ligne_g = QHBoxLayout()
        self.chk_gite = QCheckBox("Viser une gîte de")
        self.chk_gite.setChecked(True)
        self.chk_gite.toggled.connect(lambda v: self.sp_gite.setEnabled(v))
        self.sp_gite = SpinNombre()
        self.sp_gite.setRange(-15.0, 15.0)
        self.sp_gite.setDecimals(1)
        self.sp_gite.setSingleStep(0.5)
        self.sp_gite.setSuffix(" °")
        self.sp_gite.setValue(0.0)
        self.sp_gite.setToolTip(
            "0° : navire droit — c'est ce qu'on veut presque toujours. Une "
            "gîte non nulle se vise à dessein : travaux sur la coque, une "
            "prise d'eau à dégager, une passerelle à mettre à hauteur "
            "(bâbord négatif, tribord positif, jusqu'à ±15°). Décochez pour "
            "laisser la gîte libre et ne chercher que l'assiette, le GM et "
            "l'économie d'eau.")
        ligne_g.addWidget(self.chk_gite)
        ligne_g.addWidget(self.sp_gite)
        ligne_g.addWidget(QLabel("(0 = gîte nulle)"))
        ligne_g.addStretch(1)
        lay.addLayout(ligne_g)

        ligne = QHBoxLayout()
        self.chk_assiette = QCheckBox("Viser une assiette de")
        self.chk_assiette.setChecked(True)
        self.chk_assiette.toggled.connect(
            lambda v: self.sp_assiette.setEnabled(v))
        self.sp_assiette = SpinNombre()
        self.sp_assiette.setRange(-5.0, 5.0)
        self.sp_assiette.setDecimals(2)
        self.sp_assiette.setSingleStep(0.05)
        self.sp_assiette.setSuffix(" m")
        self.sp_assiette.setValue(0.30)
        self.sp_assiette.setToolTip(
            "Convention du dossier : assiette positive = enfoncement arrière. "
            "Décochez pour laisser le solveur libre de l'assiette et ne "
            "chercher que la gîte, le GM et l'économie d'eau.")
        ligne.addWidget(self.chk_assiette)
        ligne.addWidget(self.sp_assiette)
        ligne.addStretch(1)
        lay.addLayout(ligne)
        return card

    def _carte_ballasts(self):
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 14)
        t = QLabel("Ballasts sur lesquels jouer")
        t.setObjectName("cardTitle")
        lay.addWidget(t)

        barre = QHBoxLayout()
        b_tous = QPushButton("Tout cocher")
        b_tous.setProperty("ghost", "1")
        b_tous.clicked.connect(lambda: self._cocher(True))
        b_aucun = QPushButton("Tout décocher")
        b_aucun.setProperty("ghost", "1")
        b_aucun.clicked.connect(lambda: self._cocher(False))
        barre.addWidget(b_tous)
        barre.addWidget(b_aucun)
        barre.addStretch(1)
        lay.addLayout(barre)

        zone = QScrollArea()
        zone.setWidgetResizable(True)
        zone.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        grille = QGridLayout(inner)
        grille.setContentsMargins(0, 0, 0, 0)
        grille.setHorizontalSpacing(18)
        grille.setVerticalSpacing(3)
        zone.setWidget(inner)
        zone.setMinimumHeight(120)
        zone.setMaximumHeight(170)
        lay.addWidget(zone)

        self.cases = {}
        nav = getattr(self.win, "nav", None)
        noms = ballast.ballasts_du_navire(nav) if nav is not None else []
        if not noms:
            lay.addWidget(QLabel(
                "Aucune capacité déclarée « ballast » avec table de jaugeage "
                "dans ce navire : rien à ballaster. Le repère se règle dans "
                "« Créer ou modifier le navire… › Capacités » (colonne "
                "Ballast)."))
            return card
        actuel = {t.capacite: t for t in self.win.condition.tanks}
        for i, nom in enumerate(noms):
            t_fill = actuel.get(nom)
            # la capacité TELLE QUE CHARGÉE : c'est à la densité du point que
            # le solveur va peser ce ballast, l'infobulle doit dire la même
            cap = (t_fill.capacite_chargee(nav) if t_fill is not None
                   else nav.capacity(nom))
            plein = cap.at_fill_pc(100.0)
            c = QCheckBox(nom)
            c.setChecked(True)
            pc = t_fill.fill_pc(nav) if t_fill else 0.0
            d = (f"densité {densite_texte(cap.density)}"
                 + (f" relevée à ce point (dossier : "
                    f"{densite_texte(cap.densite_dossier)})"
                    if t_fill is not None and t_fill.densite_modifiee(nav)
                    else " (dossier)"))
            c.setToolTip(
                f"{plein['Volume_m3']:.1f} m³ · {plein['Poids_t']:.1f} t pleine\n"
                f"LCG {plein['LCG_m']:.2f} m · TCG {plein.get('TCG_m', 0):+.2f} m"
                f" · VCG {plein.get('VCG_m', 0):.2f} m\n"
                f"FSM max {cap.fsm_max_tm:.1f} t.m · relevé actuel {pc:.0f} %"
                f" · {d}")
            self.cases[nom] = c
            grille.addWidget(c, i // 3, i % 3)
        return card

    def _cocher(self, etat):
        for c in self.cases.values():
            c.setChecked(etat)

    # ------------------------------------------------------------- affichage
    def _vider(self):
        while self.compte.count():
            item = self.compte.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _dire(self, texte, style="", gras=False):
        lbl = QLabel(texte)
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        if style == "hint":
            lbl.setObjectName("hint")
        elif style:
            lbl.setStyleSheet(f"color: {style};"
                              + (" font-weight: bold;" if gras else ""))
        elif gras:
            lbl.setStyleSheet("font-weight: bold;")
        self.compte.addWidget(lbl)
        return lbl

    # ------------------------------------------------------------- exécution
    def run(self):
        self._vider()
        self.btn_apply.setEnabled(False)
        nav = getattr(self.win, "nav", None)
        if nav is None:
            self._dire("Le navire n'a pas ses tables hydrostatiques : aucun "
                       "calcul possible.", theme.WARN)
            return
        choisis = [n for n, c in self.cases.items() if c.isChecked()]
        if not choisis:
            self._dire("Aucun ballast coché : rien à chercher.", theme.WARN)
            return

        cond = self.win.condition.to_core(nav, self.win.project)
        reglages = ballast.Reglages(
            tanks=choisis,
            transfert_seul=self.rb_transfert.isChecked(),
            gite_cible_deg=(self.sp_gite.value()
                            if self.chk_gite.isChecked() else None),
            assiette_cible_m=(self.sp_assiette.value()
                              if self.chk_assiette.isChecked() else None))
        self.btn_run.setEnabled(False)
        self.btn_run.setText("Recherche…")
        try:
            self.rapport = ballast.resoudre(nav, cond, reglages)
        except Exception as e:
            # une table de jaugeage bancale ne doit pas faire tomber la
            # fenêtre : le compte rendu dit ce qui a échoué
            self.rapport = None
            self._vider()
            self._dire(f"La recherche a échoué : {e}", theme.DANGER, gras=True)
            self._dire("Vérifiez les tables de jaugeage des ballasts cochés et "
                       "le domaine des tables hydrostatiques.", "hint")
            return
        finally:
            self.btn_run.setEnabled(True)
            self.btn_run.setText("Chercher")
        self._rendre(self.rapport)
        self.btn_apply.setEnabled(bool(self.rapport.operations)
                                  and self.rapport.arrivee is not None
                                  and self.rapport.arrivee.dans_domaine)

    def _rendre(self, rap):
        self._vider()
        if rap.depart is None or rap.arrivee is None:
            for m in rap.messages:
                self._dire("• " + m, theme.WARN)
            return
        d, a = rap.depart, rap.arrivee

        self._dire("Avant → après", gras=True)
        cible = self.sp_gite.value() if self.chk_gite.isChecked() else 0.0
        for libelle, av, ap, unite, mieux in _comparaison(d, a, cible):
            fleche = "→"
            couleur = theme.OK if mieux else (theme.TEXT_DIM if mieux is None
                                              else theme.WARN)
            self._dire(
                f"<span style='color:{theme.TEXT_DIM}'>{libelle}</span> &nbsp; "
                f"{av}{unite} &nbsp;{fleche}&nbsp; "
                f"<b style='color:{couleur}'>{ap}{unite}</b>")

        if not a.dans_domaine:
            self._dire("Configuration hors du domaine des tables : "
                       "inexploitable.", theme.DANGER, gras=True)

        self._dire("Manœuvres", gras=True)
        if not rap.operations:
            self._dire("   Aucune : le ballastage actuel est déjà le meilleur "
                       "des essais.", "hint")
        for nom, av, ap in rap.operations:
            verbe = "Remplir" if ap > av else "Vider"
            self._dire(f"   {verbe} {nom} de {abs(ap - av):.1f} m³ "
                       f"({av:.1f} → {ap:.1f} m³)")

        for m in rap.messages:
            self._dire("• " + m, "hint")
        self._dire(f"{rap.evaluations} configurations évaluées en "
                   f"{rap.duree_s:.1f} s.", "hint")

    # ------------------------------------------------------------- résultat
    def appliquer(self):
        """Écrit le ballastage retenu dans la condition, en volumes.

        Le volume est la grandeur que l'on commande à la pompe ; la sonde se
        relèvera après la manœuvre et remplacera cette valeur."""
        rap = self.rapport
        if rap is None or rap.arrivee is None:
            return 0
        nav = self.win.nav
        cond = self.win.condition
        n = 0
        for nom, pc in rap.arrivee.remplissages.items():
            # le VOLUME ne dépend pas de la densité (c'est la géométrie de la
            # capacité) : on peut le lire sur la capacité du dossier. La
            # densité relevée au point, elle, n'est pas touchée — le solveur a
            # compté avec, et la manœuvre ne change pas l'eau qu'on a prise.
            vol = nav.capacity(nom).at_fill_pc(pc)["Volume_m3"]
            existant = next((t for t in cond.tanks if t.capacite == nom), None)
            if existant is None:
                cond.tanks.append(TankFill(nom, VOLUME, vol))
            else:
                existant.mesure, existant.valeur = VOLUME, vol
            n += 1
        return n


def _comparaison(d, a, gite_cible_deg=0.0):
    """Lignes avant/après. `mieux` vaut True/False/None (indifférent) — pour
    la gîte, « mieux » se juge à la distance de la gîte VISÉE, pas de zéro."""
    def g(e):
        return "—" if e.gite_deg != e.gite_deg else f"{e.gite_deg:+.2f}"
    return [
        ("Gîte", g(d), g(a), " °",
         abs(a.gite_deg - gite_cible_deg) < abs(d.gite_deg - gite_cible_deg)),
        ("Assiette", f"{d.assiette_m:+.3f}", f"{a.assiette_m:+.3f}", " m", None),
        ("Tirant d'eau AR", _te(d.te_ar_m), _te(a.te_ar_m), " m", None),
        ("Tirant d'eau AV", _te(d.te_av_m), _te(a.te_av_m), " m", None),
        ("Déplacement", f"{d.poids_t:.1f}", f"{a.poids_t:.1f}", " t", None),
        ("GM corrigé", f"{d.gm_corrige_m:.3f}", f"{a.gm_corrige_m:.3f}", " m",
         a.gm_corrige_m >= d.gm_corrige_m),
        ("Carènes liquides ΣFSM", f"{d.fsm_total_tm:.1f}",
         f"{a.fsm_total_tm:.1f}", " t.m", a.fsm_total_tm <= d.fsm_total_tm),
        ("Eau de ballast", f"{d.eau_m3:.1f}", f"{a.eau_m3:.1f}", " m³",
         a.eau_m3 <= d.eau_m3),
        ("Ballasts partiels", str(len(d.slack)), str(len(a.slack)), "",
         len(a.slack) <= len(d.slack)),
    ]


def _te(v):
    return "—" if v is None else f"{float(v):.2f}"
