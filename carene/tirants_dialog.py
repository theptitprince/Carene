# -*- coding: utf-8 -*-
"""Le relevé de tirants d'eau du bord, et le poids fictif qui en sort (D-60).

On marque les tirants d'eau lus à la coque ; Carène les ramène aux
perpendiculaires, entre dans la table, et dit **de combien** le navire est
plus lourd (ou plus léger) que ce que le chargement déclare, et **où** ce
poids se trouve. Rien n'est appliqué tant qu'on n'a pas cliqué « Ajouter ce
poids fictif » : le calcul reste celui de l'officier, la mesure ne fait que
l'interpeller.
"""
from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from . import theme
from .condition_model import ExtraWeight
from .core import tirants_releves as _tr
from .project import KIND_CONTOUR
from .saisie import SpinNombre

NOM_POIDS = _tr.NOM_POIDS


def nom_du_poids(ecart, date=""):
    """Le nom du poids fictif dit d'où il vient : sans cela, c'est un poids
    mystérieux de plus dans le bilan six mois plus tard."""
    quand = f" du {date}" if date else ""
    return (f"{NOM_POIDS}{quand} (AR {ecart.te_ar_pp_m:.2f} / "
            f"AV {ecart.te_av_pp_m:.2f} m aux PP)")


class TirantsDialog(QDialog):
    """Saisie du relevé, compte rendu de l'écart, et application du poids."""

    def __init__(self, win, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.ecart = None
        self.setWindowTitle("Tirants d'eau relevés")
        self.resize(760, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        titre = QLabel("Correction par les tirants d'eau relevés")
        titre.setStyleSheet("font-size: 18px; font-weight: bold;")
        root.addWidget(titre)
        intro = QLabel(
            "Relevez les tirants d'eau <b>aux repères peints</b> : Carène les "
            "ramène aux perpendiculaires, lit la table à cette assiette, et "
            "compare au chargement déclaré. L'écart est rendu comme un "
            "<b>poids fictif</b> — une masse et une position. Ce que les "
            "tirants d'eau ne mesurent pas (la hauteur du centre de gravité), "
            "Carène ne l'invente pas : le poids est posé au KG du point, il "
            "ne change donc ni le KG ni la gîte.")
        intro.setObjectName("hint")
        intro.setWordWrap(True)
        root.addWidget(intro)

        root.addWidget(self._carte_saisie())

        self.compte = QLabel("")
        self.compte.setWordWrap(True)
        self.compte.setTextFormat(Qt.TextFormat.RichText)
        self.compte.setAlignment(Qt.AlignmentFlag.AlignTop)
        cadre = QFrame()
        cadre.setObjectName("card")
        lay = QVBoxLayout(cadre)
        lay.setContentsMargins(14, 12, 14, 14)
        t = QLabel("Ce que la coque dit")
        t.setObjectName("cardTitle")
        lay.addWidget(t)
        lay.addWidget(self.compte)
        root.addWidget(cadre, 1)

        row = QHBoxLayout()
        self.btn_calc = QPushButton("Calculer l'écart")
        self.btn_calc.setProperty("accent", "1")
        self.btn_calc.clicked.connect(self.calculer)
        self.btn_apply = QPushButton("Ajouter ce poids fictif")
        self.btn_apply.setProperty("accent", "1")
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self.appliquer)
        b_close = QPushButton("Fermer")
        b_close.clicked.connect(self.reject)
        row.addWidget(self.btn_calc)
        row.addStretch(1)
        row.addWidget(b_close)
        row.addWidget(self.btn_apply)
        root.addLayout(row)

        self._charger_releve()
        self._dire("Saisissez les tirants d'eau lus, puis « Calculer l'écart ».")

    # --------------------------------------------------------------- saisie
    def _carte_saisie(self):
        card = QFrame()
        card.setObjectName("card")
        g = QGridLayout(card)
        g.setContentsMargins(14, 12, 14, 14)
        g.setHorizontalSpacing(12)
        t = QLabel("Ce que vous lisez à la coque")
        t.setObjectName("cardTitle")
        g.addWidget(t, 0, 0, 1, 4)

        def spin(suffixe, mini, maxi, dec, pas):
            s = SpinNombre()
            s.setRange(mini, maxi)
            s.setDecimals(dec)
            s.setSingleStep(pas)
            s.setSuffix(suffixe)
            return s

        reperes = ((getattr(self.win.nav, "manifest", None) or {})
                   .get("dimensions", {}).get("reperes_tirants_eau") or {}) \
            if getattr(self.win, "nav", None) is not None else {}
        self.sp_ar = spin(" m", 0.0, 30.0, 3, 0.01)
        self.sp_av = spin(" m", 0.0, 30.0, 3, 0.01)
        self.sp_mil = spin(" m", 0.0, 30.0, 3, 0.01)
        self.chk_mil = QCheckBox("Tirant d'eau au milieu")
        self.chk_mil.setToolTip(
            "Facultatif : il ne sert pas au calcul (les tables sont à deux "
            "entrées, assiette et tirant d'eau), mais il mesure la flèche de "
            "la coque — tonture ou contre-tonture — et Carène la signale.")
        self.chk_mil.toggled.connect(self.sp_mil.setEnabled)
        self.sp_mil.setEnabled(False)
        self.chk_dens = QCheckBox("Densité de l'eau du port")
        self.chk_dens.setToolTip(
            "Facultatif : sans elle, le déplacement est lu à la densité des "
            "tables du dossier. Un port en eau saumâtre à 1,010 change le "
            "déplacement de 1,5 % — soit une vingtaine de tonnes.")
        self.sp_dens = spin("", 0.900, 1.100, 4, 0.001)
        self.sp_dens.setValue(_tr.DENSITE_MER)
        self.sp_dens.setEnabled(False)
        self.chk_dens.toggled.connect(self.sp_dens.setEnabled)
        self.chk_pp = QCheckBox("Valeurs déjà ramenées aux perpendiculaires")
        self.chk_pp.setToolTip(
            "Cochez si vos lectures sont déjà corrigées (relevé d'un autre "
            "logiciel). Par défaut, Carène considère qu'elles sont prises aux "
            "repères peints et les ramène elle-même.")

        def etiquette(cle, defaut):
            brut = str(reperes.get(cle) or "").strip()
            return f"{defaut} — repère {brut}" if brut else defaut

        g.addWidget(QLabel(etiquette("arriere", "Tirant d'eau arrière")), 1, 0)
        g.addWidget(self.sp_ar, 1, 1)
        g.addWidget(QLabel(etiquette("avant", "Tirant d'eau avant")), 1, 2)
        g.addWidget(self.sp_av, 1, 3)
        g.addWidget(self.chk_mil, 2, 0)
        g.addWidget(self.sp_mil, 2, 1)
        g.addWidget(self.chk_dens, 2, 2)
        g.addWidget(self.sp_dens, 2, 3)
        g.addWidget(self.chk_pp, 3, 0, 1, 4)
        # LES DEUX BORDS (D-80) : facultatif, un seul bord suffit. Coché, les
        # premières valeurs sont celles de bâbord et une seconde rangée prend
        # tribord ; le calcul prend la moyenne, qui efface une gîte.
        self.chk_bords = QCheckBox("Relevé des deux bords (les valeurs ci-dessus "
                                   "sont alors celles de bâbord)")
        self.chk_bords.setToolTip(
            "Facultatif : un seul bord suffit navire droit. Avec une gîte, les "
            "deux bords relevés en donnent la moyenne, qui en efface l'effet — "
            "et Carène dit la gîte apparente.")
        self.sp_ar_td = spin(" m", 0.0, 30.0, 3, 0.01)
        self.sp_av_td = spin(" m", 0.0, 30.0, 3, 0.01)
        self.sp_mil_td = spin(" m", 0.0, 30.0, 3, 0.01)
        self.lbl_td = [QLabel("Tribord : arrière"), QLabel("Tribord : avant"),
                       QLabel("Tribord : milieu")]
        g.addWidget(self.chk_bords, 4, 0, 1, 4)
        g.addWidget(self.lbl_td[0], 5, 0)
        g.addWidget(self.sp_ar_td, 5, 1)
        g.addWidget(self.lbl_td[1], 5, 2)
        g.addWidget(self.sp_av_td, 5, 3)
        g.addWidget(self.lbl_td[2], 6, 0)
        g.addWidget(self.sp_mil_td, 6, 1)

        def bords(*_a):
            deux = self.chk_bords.isChecked()
            for w in (self.sp_ar_td, self.sp_av_td, self.lbl_td[0], self.lbl_td[1]):
                w.setVisible(deux)
            mil = deux and self.chk_mil.isChecked()
            self.sp_mil_td.setVisible(mil)
            self.lbl_td[2].setVisible(mil)
            if deux and self.sp_ar_td.value() == 0.0:
                self.sp_ar_td.setValue(self.sp_ar.value())
                self.sp_av_td.setValue(self.sp_av.value())
                self.sp_mil_td.setValue(self.sp_mil.value())
        self.chk_bords.toggled.connect(bords)
        self.chk_mil.toggled.connect(bords)
        bords()
        # UNE SAISIE CHANGÉE PÉRIME L'ÉCART (P-6) : corriger une faute de frappe
        # après « Calculer l'écart » laissait « Ajouter » appliquer l'ancien
        # écart tout en archivant le nouveau relevé (60 t posées pour 146 t
        # relevées). On grise « Ajouter » jusqu'au prochain calcul.
        for s in (self.sp_ar, self.sp_av, self.sp_mil, self.sp_dens,
                  self.sp_ar_td, self.sp_av_td, self.sp_mil_td):
            s.valueChanged.connect(self._perimer)
        for c in (self.chk_mil, self.chk_dens, self.chk_pp, self.chk_bords):
            c.toggled.connect(self._perimer)
        return card

    def _perimer(self, *_a):
        if getattr(self, "ecart", None) is None:
            return
        self.ecart = None
        if hasattr(self, "btn_apply"):
            self.btn_apply.setEnabled(False)
        self._dire("Saisie modifiée : recalculez l'écart avant de l'ajouter.")

    def _charger_releve(self):
        """Rouvrir la fenêtre sur le relevé déjà saisi pour ce point."""
        brut = getattr(self.win.condition, "tirants_releves", None)
        if not brut:
            # à défaut, les tirants d'eau calculés : on part de ce que le
            # logiciel croit, le bord corrige ce qu'il lit vraiment
            eq = (self.win._last or (None, None, None, None))[1]
            if eq is not None:
                self.sp_ar.setValue(float((eq.hydro or {}).get("TE_AR_m", eq.draft_m)))
                self.sp_av.setValue(float((eq.hydro or {}).get("TE_AV_m", eq.draft_m)))
            return
        r = _tr.Releve.from_dict(brut)
        self.sp_ar.setValue(r.te_ar_m)
        self.sp_av.setValue(r.te_av_m)
        if r.te_milieu_m is not None:
            self.chk_mil.setChecked(True)
            self.sp_mil.setValue(r.te_milieu_m)
        if r.densite_eau is not None:
            self.chk_dens.setChecked(True)
            self.sp_dens.setValue(r.densite_eau)
        self.chk_pp.setChecked(r.aux_perpendiculaires)
        if r.deux_bords:
            self.chk_bords.setChecked(True)
            self.sp_ar_td.setValue(r.te_ar_td_m)
            self.sp_av_td.setValue(r.te_av_td_m)
            if r.te_milieu_td_m is not None:
                self.sp_mil_td.setValue(r.te_milieu_td_m)

    def releve(self):
        deux = self.chk_bords.isChecked()
        mil = self.chk_mil.isChecked()
        return _tr.Releve(
            te_ar_m=self.sp_ar.value(), te_av_m=self.sp_av.value(),
            te_milieu_m=self.sp_mil.value() if mil else None,
            te_ar_td_m=self.sp_ar_td.value() if deux else None,
            te_av_td_m=self.sp_av_td.value() if deux else None,
            te_milieu_td_m=self.sp_mil_td.value() if (deux and mil) else None,
            densite_eau=self.sp_dens.value() if self.chk_dens.isChecked() else None,
            aux_perpendiculaires=self.chk_pp.isChecked(),
            date=_dt.date.today().strftime("%d/%m/%Y"))

    # -------------------------------------------------------------- calcul
    def calculer(self):
        win = self.win
        nav = getattr(win, "nav", None)
        if nav is None:
            self._dire("Aucun navire chargé : rien à comparer.", mauvais=True)
            return None
        try:
            poids, lcg, _tcg, _vcg = self.chargement_declare()
        except Exception as exc:                       # pragma: no cover
            self._dire(f"Chargement non calculable : {exc}", mauvais=True)
            return None
        if poids <= 0:
            self._dire("Rien n'est embarqué : le relevé n'a rien à corriger.",
                       mauvais=True)
            return None
        self.ecart = _tr.comparer(nav, self.releve(), poids, lcg)
        self.btn_apply.setEnabled(bool(self.ecart.position_fiable))
        self._rendre_compte(self.ecart)
        return self.ecart

    def chargement_declare(self):
        """(poids, LCG, TCG, VCG) du chargement DÉCLARÉ, poids fictif exclu.

        C'est contre lui, et non contre le total courant, que la coque est
        confrontée : sans cela, corriger une première fois puis relever de
        nouveau comparerait la coque à elle-même, et le second poids fictif
        effacerait le premier au lieu de le remplacer (vu au banc d'essai).
        L'écart affiché est donc toujours le même tant que le chargement
        déclaré ne bouge pas — qu'on l'ait appliqué ou non."""
        win = self.win
        poids, lcg, tcg, vcg, _fsm = win.condition.to_core(
            win.nav, win.project).totals()
        fictifs = self.poids_fictifs()
        w = sum(f.poids_t for f in fictifs)
        if abs(w) < 1e-9:
            return poids, lcg, tcg, vcg
        declare = poids - w
        if abs(declare) < 1e-9:
            return declare, lcg, tcg, vcg
        m = poids * lcg - sum(f.poids_t * f.lcg_m for f in fictifs)
        # le poids fictif est posé au KG et au TCG du point : les retirer ne
        # les change pas, et on garde donc ceux du total
        return declare, m / declare, tcg, vcg

    def poids_fictifs(self):
        """Les poids fictifs déjà posés sur ce point (il ne devrait y en avoir
        qu'un, mais un fichier ancien peut en porter plusieurs)."""
        return [e for e in self.win.condition.extras
                if str(e.nom).startswith(NOM_POIDS)]

    def _rendre_compte(self, ec):
        c_ok, c_ko, c_att = theme.OK, theme.DANGER, theme.WARN
        lignes = []
        pos = (f"x = <b>{ec.position_m:.2f} m</b> {self._situer(ec.position_m)}"
               if ec.position_fiable else "position indéterminable")
        if ec.concordent:
            lignes.append(f"<p style='color:{c_ok}; font-size:15px'><b>Les tirants "
                          "d'eau relevés concordent avec le chargement calculé.</b></p>")
        else:
            couleur = c_ko if abs(ec.masse_pc) >= _tr.MASSE_FORTE_PC else c_att
            lignes.append(
                f"<p style='color:{couleur}; font-size:15px'><b>Poids fictif : "
                f"{ec.masse_t:+.1f} t</b> ({ec.masse_pc:+.2f} % du déplacement), "
                f"{pos}.</p>")
        lignes.append(
            "<table cellpadding='3'>"
            + self._ligne("Relevé ramené aux perpendiculaires",
                          f"AR {ec.te_ar_pp_m:.3f} m · AV {ec.te_av_pp_m:.3f} m · "
                          f"milieu {ec.te_milieu_pp_m:.3f} m · assiette {ec.assiette_m:+.3f} m")
            + self._ligne("Déplacement lu dans la table",
                          f"{ec.deplacement_observe_t:,.1f} t".replace(",", " ")
                          + f" · LCB {ec.lcb_observe_m:.3f} m")
            + self._ligne("Déplacement déclaré au point",
                          f"{ec.deplacement_calcule_t:,.1f} t".replace(",", " ")
                          + f" · LCG {ec.lcg_calcule_m:.3f} m")
            + self._ligne("Écart", f"{ec.masse_t:+.1f} t · moment {ec.moment_tm:+.0f} t·m")
            + (self._ligne("Densité de l'eau",
                           f"{ec.densite_eau:.4f} (tables : {ec.densite_tables:g})")
               if ec.densite_eau else "")
            + (self._ligne("Flèche au milieu", f"{ec.tonture_m * 100:+.0f} cm")
               if ec.tonture_m is not None else "")
            + (self._ligne("Repères", "1 cm de tirant d'eau = "
                           f"{ec.tpc_t_cm:.2f} t" if ec.tpc_t_cm else "")
               if ec.tpc_t_cm else "")
            + "</table>")
        deja = self.poids_fictifs()
        if deja:
            porte = sum(f.poids_t for f in deja)
            lignes.append(
                f"<p style='color:{theme.TEXT_DIM}'>Ce point porte déjà un poids "
                f"fictif de {porte:+.1f} t : l'écart ci-dessus est celui du "
                "chargement <b>déclaré</b> (ce poids exclu), de sorte qu'un "
                "nouveau relevé le <b>remplace</b> et ne s'y ajoute pas.</p>")
        for a in ec.alertes:
            lignes.append(f"<p style='color:{c_ko}'>⚠ {a}</p>")
        for r in ec.remarques:
            lignes.append(f"<p style='color:{theme.TEXT_DIM}'>{r}</p>")
        if ec.position_fiable and not ec.concordent:
            lignes.append(
                f"<p style='color:{theme.TEXT_DIM}'>« Ajouter ce poids fictif » "
                "le pose dans les poids divers du point, au KG et au TCG "
                "actuels : le déplacement et l'assiette rejoignent la coque, "
                "le KG et la gîte ne bougent pas — les tirants d'eau ne les "
                "mesurent pas. Ce poids s'efface comme n'importe quel autre.</p>")
        self.compte.setText("".join(lignes))

    def _situer(self, x):
        """Où tombe le poids fictif, dit avec les repères du bord : le couple
        le plus proche, et la cale s'il tombe dedans."""
        bouts = []
        # `table_couples` est la liste des abscisses, index = numéro de couple
        couples = getattr(self.win, "table_couples", None) or []
        if couples:
            n = min(range(len(couples)), key=lambda i: abs(couples[i] - x))
            bouts.append(f"sur le couple {n}" if abs(couples[n] - x) <= 0.05
                         else f"vers le couple {n}")
        try:
            for deck in self.win.project.sorted_decks():
                for cap in deck.capacities:
                    if len(cap.points) < 3 or cap.kind == KIND_CONTOUR:
                        continue
                    xs = [p[0] for p in cap.points]
                    if min(xs) <= x <= max(xs):
                        bouts.append(f"au droit de {cap.code}")
                        raise StopIteration
        except StopIteration:
            pass
        except Exception:                              # pragma: no cover
            pass
        return f"({', '.join(bouts)})" if bouts else ""

    # ---------------------------------------------------------- appliquer
    def appliquer(self):
        """Pose le poids fictif dans les poids divers du point.

        Au KG et au TCG du point : un poids qu'on ne sait pas situer en
        hauteur ne doit pas déplacer le centre de gravité vertical (D-60). Un
        écart déjà corrigé est REMPLACÉ, jamais empilé — sans quoi deux
        relevés successifs compteraient deux fois la même tonne."""
        # toujours recalculé sur la saisie du moment : l'écart posé est celui
        # du relevé archivé, jamais celui d'une saisie précédente
        ec = self.calculer()
        if ec is None or not ec.position_fiable:
            return None
        win = self.win
        _p, _lcg, tcg, vcg = self.chargement_declare()
        win.condition.extras[:] = [e for e in win.condition.extras
                                   if not str(e.nom).startswith(NOM_POIDS)]
        poids = ExtraWeight(nom=nom_du_poids(ec, self.releve().date),
                            poids_t=round(ec.masse_t, 3),
                            lcg_m=round(ec.position_m, 3),
                            tcg_m=round(tcg, 3), vcg_m=round(vcg, 3))
        win.condition.extras.append(poids)
        win.condition.tirants_releves = self.releve().to_dict()
        win._dirty = True              # le point est modifié (P-5)
        win._refresh_saisies()
        win.recompute()
        self.accept()
        return poids

    # ------------------------------------------------------------- détails
    @staticmethod
    def _ligne(libelle, valeur):
        return (f"<tr><td style='color:{theme.TEXT_DIM}'>{libelle}</td>"
                f"<td><b>{valeur}</b></td></tr>")

    def _dire(self, texte, mauvais=False):
        couleur = theme.DANGER if mauvais else theme.TEXT_DIM
        self.compte.setText(f"<p style='color:{couleur}'>{texte}</p>")
