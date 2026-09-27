# -*- coding: utf-8 -*-
"""Plan propre à une cale : import d'un plan (DXF, PDF ou image) et calage dans le repère navire.

Quand plusieurs cales partagent un même pont, travailler sur le plan du pont
entier est peu lisible. Cette boîte de dialogue associe à UNE capacité sa
propre vue de dessus, calée en X-Y, qui servira de fond au placement des
palettes.

Deux façons de caler :

- **par points de référence** (précis) : on clique 2 ou 3 points repérables sur
  l'image et on saisit leurs coordonnées navire — même principe que le calage
  des plans de ponts ;
- **sur le rectangle englobant** (rapide) : on déclare que l'image couvre
  exactement le rectangle englobant du polygone de la cale. Suffisant quand le
  plan a été recadré au plus juste.

Dans les deux cas le polygone de la capacité est superposé en surimpression :
s'il ne tombe pas sur le dessin, le calage est faux et cela se voit tout de
suite.

Le curseur **s'accroche aux traits** du fond quand celui-ci est vectoriel (PDF
ou DXF), et aux sommets du polygone de la cale : 8 pixels d'écran, Maj pour
suspendre — exactement les mêmes gestes que la fenêtre de décalquage (D-24).
Un point de calage cliqué à l'œil coûte quelques centimètres d'erreur sur le
placement des palettes ; le même point accroché au trait n'en coûte aucun.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QGraphicsEllipseItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from . import pdf_plan, theme
from .dialogs import CalPointDialog, TraitsConstructionDialog
from .geometry import Calibration
from .items import SnapMarkerItem
from .project import Calibrated
from .scene import (SNAP_PX, VuePlanBase, accrocher, chargeur,
                    groupe_de_construction, index_local, source_traits)

FILTRE_PLANS_CALE = (
    "Plans (*.dxf *.pdf *.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff);;"
    "DXF (*.dxf);;PDF (*.pdf);;Images (*.png *.jpg *.jpeg *.bmp *.gif);;"
    "DWG — à convertir en DXF au préalable (*.dwg);;Tous les fichiers (*)")


class _ImageView(VuePlanBase):
    """Vue de l'image : molette = zoom au curseur, bouton du milieu = déplacer,
    clic gauche = point de calage.

    Mêmes gestes que la fenêtre de décalquage : on ne réapprend pas la souris
    d'un écran à l'autre — et, depuis `VuePlanBase`, c'est le même code, pas
    une copie qui dérivera."""

    def __init__(self, on_click, parent=None, on_move=None):
        super().__init__(parent)
        self._on_click = on_click
        self._on_move = on_move
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(self.renderHints())
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor(theme.BG_DEEP)))
        self.setMouseTracking(True)      # l'accroche se voit avant de cliquer

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_click(self.mapToScene(event.position().toPoint()),
                           event.modifiers())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_move(event):
            return
        if self._on_move is not None:
            self._on_move(self.mapToScene(event.position().toPoint()),
                          event.modifiers())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning and event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class CaleImageDialog(QDialog):
    """Associe un plan calé à une capacité. `values()` renvoie un Calibrated."""

    def __init__(self, capacity, parent=None, ship_folder=""):
        super().__init__(parent)
        self.capacity = capacity
        self.ship_folder = ship_folder      # où ranger un PDF ou un DXF rendu
        self.setWindowTitle(f"Plan de la cale — {capacity.code}")
        self.resize(1000, 720)

        src = capacity.plan
        self.result_plan = src.copy() if src else Calibrated(axes=("X", "Y"))

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        hint = QLabel(
            "Importez la vue de dessus de cette cale (DXF, PDF ou image), puis "
            "calez-la : cliquez 2 à 3 points repérables et saisissez leurs "
            "coordonnées navire. Le curseur s'accroche aux traits du plan et "
            "aux sommets de la cale — Maj pour suspendre. Le contour de la "
            "cale s'affiche en surimpression : il doit tomber sur le dessin.")
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        root.addWidget(hint)

        self.view = _ImageView(self._on_click, on_move=self._on_move)
        root.addWidget(self.view, 1)

        # ligne d'état du curseur : même rôle que la barre d'état du
        # décalquage — on doit voir qu'on est accroché avant de cliquer
        self.lbl_snap = QLabel("")
        self.lbl_snap.setObjectName("hint")
        root.addWidget(self.lbl_snap)

        self.lbl_state = QLabel("")
        self.lbl_state.setWordWrap(True)
        root.addWidget(self.lbl_state)

        row = QHBoxLayout()
        row.setSpacing(9)
        b_img = QPushButton("Importer un plan…")
        b_img.setProperty("accent", "1")
        b_img.clicked.connect(self.pick_image)
        b_bbox = QPushButton("Caler sur le rectangle englobant")
        b_bbox.setProperty("ghost", "1")
        b_bbox.clicked.connect(self.fit_to_bbox)
        b_reset = QPushButton("Effacer les points")
        b_reset.setProperty("ghost", "1")
        b_reset.clicked.connect(self.clear_points)
        b_traits = QPushButton("Traits de construction…")
        b_traits.setProperty("ghost", "1")
        b_traits.setToolTip(
            "Les droites qu'on tire pour décalquer : ligne de foi, couples, "
            "cotes reportées. Le curseur s'accroche aux traits, et surtout à "
            "leurs croisements.")
        b_traits.clicked.connect(self.open_traits)
        b_del = QPushButton("Retirer le plan")
        b_del.setProperty("ghost", "1")
        b_del.clicked.connect(self.remove_plan)
        for b in (b_img, b_bbox, b_reset, b_traits, b_del):
            row.addWidget(b)
        row.addStretch(1)
        b_cancel = QPushButton("Annuler")
        b_cancel.clicked.connect(self.reject)
        b_ok = QPushButton("Appliquer")
        b_ok.setProperty("accent", "1")
        b_ok.clicked.connect(self.accept)
        row.addWidget(b_cancel)
        row.addWidget(b_ok)
        root.addLayout(row)

        self._pixmap_item = None
        self._removed = False
        self._snap_marker = None
        self._local_index = None      # sommets de la cale + points de calage
        self._construction = []       # traits de construction, en pixels
        self.snap_enabled = True
        # les traits du fond se lisent en tâche de fond : le dialogue s'ouvre
        # tout de suite, l'accroche arrive quand elle est prête
        self.chargeur = chargeur()
        self.chargeur.pret.connect(self._traits_prets)
        # un plan illisible se disait dans le décalquage et pas ici : la
        # ligne d'état restait sur « Lecture des traits… » pour toujours
        self.chargeur.echec.connect(self._traits_rates)
        self.rebuild()
        self._demander_traits()

    # ---------------------------------------------------------------- actions
    def pick_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Plan de la cale", "", FILTRE_PLANS_CALE)
        if not path:
            return
        bas = path.lower()
        if bas.endswith(".dwg"):
            from .plan_editor import MESSAGE_DWG
            QMessageBox.information(self, "DWG à convertir", MESSAGE_DWG)
            return
        if bas.endswith(".dxf"):
            if not self._pick_dxf(path):
                return
        elif bas.endswith(".pdf"):
            if not self._pick_pdf(path):
                return
        else:
            # rangée dans `plans/` comme le PDF et le DXF (D-9) : un navire
            # est un dossier qu'on emporte tel quel, un chemin absolu vers le
            # bureau de l'utilisateur ne survit pas au déplacement
            from . import app_paths
            self.result_plan.image_path = app_paths.ranger_dans_plans(
                path, self._dossier_navire())
            self.result_plan.pdf_path = ""
            self.result_plan.dxf_path = ""
            self.result_plan.cal_points = []
            self.result_plan.calibration = Calibration()
        self._removed = False
        self.rebuild()
        self._demander_traits()

    def _dossier_navire(self):
        from . import app_paths
        return self.ship_folder or app_paths.ship_folder()

    def _pick_pdf(self, path) -> bool:
        """Même rendu que dans l'éditeur de plans : page choisie, image rangée
        dans `plans/` du dossier du navire, PDF gardé pour un re-rendu — et
        ses traits servent maintenant à l'accroche du curseur."""
        from .dialogs import PdfImportDialog
        try:
            dlg = PdfImportDialog(path, self)
        except Exception as e:
            QMessageBox.warning(self, "PDF illisible", str(e))
            return False
        if not dlg.exec():
            return False
        page, rot, dpi = dlg.values()
        try:
            out, dest = pdf_plan.import_into(path, page, rot, dpi,
                                             self._dossier_navire())
        except Exception as e:
            QMessageBox.warning(self, "Import PDF", str(e))
            return False
        self.result_plan = Calibrated(image_path=out, axes=("X", "Y"),
                                      pdf_path=dest, pdf_page=page,
                                      pdf_rotation=rot, pdf_dpi=dpi)
        return True

    def _pick_dxf(self, path) -> bool:
        """Import d'un DXF : choix des calques, rendu, et calage déduit des
        coordonnées du dessin s'il porte son unité (D-9)."""
        from . import dxf_plan
        from .dialogs import DxfImportDialog
        try:
            dlg = DxfImportDialog(path, self, axes=("X", "Y"))
        except Exception as e:
            QMessageBox.warning(self, "DXF illisible", str(e))
            return False
        if not dlg.exec():
            return False
        calques, largeur, auto, decalage = dlg.values()
        try:
            out, dest, w, h, origine, res = dxf_plan.import_into(
                path, self._dossier_navire(), calques=calques,
                largeur_cible=largeur)
        except Exception as e:
            QMessageBox.warning(self, "Import DXF", str(e))
            return False
        plan = Calibrated(image_path=out, axes=("X", "Y"), dxf_path=dest,
                          dxf_layers=list(calques or []),
                          dxf_origin=(float(origine[0]), float(origine[1])),
                          dxf_resolution=float(res), dxf_size=(int(w), int(h)))
        if auto:
            M = dxf_plan.matrice_calage(origine, res,
                                        dlg.dessin.metres_par_unite, decalage)
            if M is not None:
                plan.calibration = Calibration(M)
        self.result_plan = plan
        return True

    def remove_plan(self):
        self._removed = True
        self.result_plan = Calibrated(axes=("X", "Y"))
        self.rebuild()
        self.lbl_snap.setText("")

    def clear_points(self):
        self.result_plan.cal_points = []
        self.result_plan.calibration = Calibration()
        self._local_index = None
        self.rebuild()

    def fit_to_bbox(self):
        """Cale l'image sur le rectangle englobant du polygone de la cale."""
        if self._pixmap_item is None:
            QMessageBox.information(self, "Plan de cale",
                                    "Importez d'abord une image.")
            return
        pts = self.capacity.points
        if len(pts) < 3:
            QMessageBox.warning(self, "Plan de cale",
                                "Cette capacité n'a pas de polygone tracé.")
            return
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        w = self._pixmap_item.pixmap().width()
        h = self._pixmap_item.pixmap().height()
        # coin haut-gauche de l'image = (Xmin, Ymax) : Y monte à l'écran
        self.result_plan.cal_points = [
            {"pixel": [0, 0], "real": [min(xs), max(ys)]},
            {"pixel": [w, h], "real": [max(xs), min(ys)]},
        ]
        self._refit()
        self.rebuild()

    # ---------------------------------------------------------------- accroche
    def _demander_traits(self):
        """Lance, s'il y a lieu, la lecture des traits du fond — en tâche de
        fond : le dialogue reste maniable pendant les quelques secondes que
        prend un plan chargé."""
        if source_traits(self.result_plan) is None:
            self._update_snap_state()
            return
        self.chargeur.demander(self.result_plan)
        self._update_snap_state()

    def _traits_prets(self, cle):
        src = source_traits(self.result_plan)
        if src is not None and src[2] == cle:
            self._update_snap_state()

    def _traits_rates(self, cle, message):
        """Les traits du fond n'ont pas pu être lus : on le dit, il reste
        l'accroche aux sommets de la cale et aux points de calage."""
        src = source_traits(self.result_plan)
        if src is not None and src[2] == cle:
            self._update_snap_state()

    def _update_snap_state(self):
        cal = self.result_plan
        if not cal.image_path:
            self.lbl_snap.setText("")
            return
        rate = self.chargeur.echec_de(cal)
        if rate:
            self.lbl_snap.setText(
                f"Traits du plan illisibles ({rate}) : accroche aux sommets "
                "de la cale et aux points de calage seulement.")
            return
        idx = self.chargeur.index(cal)
        if idx is not None:
            n = f"{len(idx):,}".replace(",", " ")
            quoi = "DXF" if cal.from_dxf else "PDF"
            self.lbl_snap.setText(
                f"Accroche : {n} sommets du {quoi} + les sommets de la cale "
                "(Maj pour suspendre).")
        elif self.chargeur.en_lecture(cal):
            self.lbl_snap.setText(
                "Lecture des traits… l'accroche aux traits du plan s'activera "
                "toute seule ; celle aux sommets de la cale marche déjà.")
        elif source_traits(cal) is not None:
            self.lbl_snap.setText(
                "Accroche : sommets de la cale (traits du plan non lus).")
        else:
            self.lbl_snap.setText(
                "Accroche : sommets de la cale et points de calage déjà posés "
                "(Maj pour suspendre) — ce fond n'est pas vectoriel.")

    def _index_local(self):
        """Sommets propres à cette vue : le polygone de la cale (quand le
        calage permet de le placer en pixels) et les points de calage déjà
        posés. Refait à chaque changement — il en compte quelques dizaines.

        Même fabrique que la scène de décalquage (`scene.index_local`, dont se
        sert `PlanScene.local_snap_index`) : ce sont les mêmes points, ils ne
        doivent pas être bâtis de deux façons."""
        if self._local_index is None:
            self._local_index = index_local(self.result_plan,
                                            [self.capacity.points])
        return self._local_index

    def _snap(self, scene_pos, modifiers):
        """(point retenu, accroché ?) : le sommet le plus proche à moins de
        SNAP_PX pixels d'écran, parmi les traits du fond vectoriel et les
        sommets de la cale — sauf Maj enfoncée. L'arbitrage (sommets d'abord,
        croisements de traits de construction ensuite) est celui du décalquage,
        `scene.accrocher` (D-24)."""
        if self._pixmap_item is None or not self.snap_enabled:
            return scene_pos, False
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            return scene_pos, False
        rayon = SNAP_PX / self.view.view_scale()
        return accrocher(scene_pos, rayon,
                         [self.chargeur.index(self.result_plan),
                          self._index_local()],
                         self._construction)

    def open_traits(self):
        """La liste des traits de construction de ce plan de cale."""
        couples = []
        if self.ship_folder:
            from . import app_paths
            couples = app_paths.table_couples(self.ship_folder)
        dlg = TraitsConstructionDialog(self, self.result_plan, couples=couples,
                                       titre=self.capacity.code)
        if dlg.exec():
            self.result_plan.traits = dlg.valeurs()
            self.rebuild()
        return dlg

    def _montrer_accroche(self, pos):
        if self._snap_marker is None:
            return
        if pos is None:
            self._snap_marker.setVisible(False)
        else:
            self._snap_marker.setPos(pos)
            self._snap_marker.setVisible(True)

    def _on_move(self, scene_pos, modifiers=Qt.KeyboardModifier.NoModifier):
        if self._pixmap_item is None:
            return
        pos, accroche = self._snap(scene_pos, modifiers)
        self._montrer_accroche(pos if accroche else None)
        parts = []
        if accroche:
            parts.append(f"accroché  ({pos.x():.1f} ; {pos.y():.1f}) px")
        cal = self.result_plan.calibration
        if cal.valid:
            x, y = cal.to_real(pos.x(), pos.y())
            parts.append(f"X = {x:8.2f} m      Y = {y:8.2f} m")
        elif not accroche:
            parts.append(f"pixel ({pos.x():.0f} ; {pos.y():.0f}) — plan non calé")
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            parts.append("accroche suspendue (Maj)")
        self.lbl_snap.setText("      ".join(parts) if parts else "")

    def _on_click(self, scene_pos, modifiers=Qt.KeyboardModifier.NoModifier):
        if self._pixmap_item is None:
            return
        scene_pos, _ = self._snap(scene_pos, modifiers)
        idx = len(self.result_plan.cal_points) + 1
        dlg = CalPointDialog(("X", "Y"), idx, self)
        if not dlg.exec():
            return
        label, x, y = dlg.values()
        self.result_plan.cal_points.append({
            "pixel": [scene_pos.x(), scene_pos.y()],
            "real": [x, y], "label": label})
        self._refit()
        self.rebuild()

    def _refit(self):
        self._local_index = None      # les sommets de la cale ont bougé
        pts = self.result_plan.cal_points
        if len(pts) < 2:
            self.result_plan.calibration = Calibration()
            return
        try:
            self.result_plan.calibration = Calibration.fit(
                [p["pixel"] for p in pts], [p["real"] for p in pts])
        except ValueError as e:
            self.result_plan.calibration = Calibration()
            QMessageBox.warning(self, "Calage", str(e))

    # ---------------------------------------------------------------- rendu
    def rebuild(self):
        sc = self.view.scene()
        sc.clear()
        self._pixmap_item = None
        self._snap_marker = None
        self._local_index = None
        path = self.result_plan.image_path
        if path and os.path.exists(path):
            pm = QPixmap(path)
            if not pm.isNull():
                self._pixmap_item = QGraphicsPixmapItem(pm)
                sc.addItem(self._pixmap_item)

        cal = self.result_plan.calibration
        if self._pixmap_item is not None and cal.valid:
            # contour de la cale en surimpression : contrôle visuel du calage
            poly = QPolygonF()
            for x, y in self.capacity.points:
                u, v = cal.to_pixel(x, y)
                poly.append(QPointF(u, v))
            item = QGraphicsPolygonItem(poly)
            pen = QPen(QColor(theme.CAP_SEL), 2.0)
            pen.setCosmetic(True)
            item.setPen(pen)
            item.setBrush(QBrush(QColor(theme.CAP_FILL)))
            sc.addItem(item)

        for i, p in enumerate(self.result_plan.cal_points, 1):
            u, v = p["pixel"]
            dot = QGraphicsEllipseItem(QRectF(u - 4, v - 4, 8, 8))
            dot.setBrush(QBrush(QColor(theme.ACCENT)))
            dot.setPen(QPen(QColor(theme.SURFACE), 1.5))
            sc.addItem(dot)
            txt = QGraphicsSimpleTextItem(p.get("label") or str(i))
            txt.setBrush(QBrush(QColor(theme.TEXT)))
            txt.setFlag(QGraphicsSimpleTextItem.GraphicsItemFlag
                        .ItemIgnoresTransformations)
            txt.setPos(u + 7, v - 8)
            sc.addItem(txt)

        self._construction = []
        if self._pixmap_item is not None:
            groupe, lignes = groupe_de_construction(
                self.result_plan, self._pixmap_item.boundingRect())
            if groupe is not None:
                sc.addItem(groupe)
                self._construction = lignes

        if self._pixmap_item is not None:
            self._snap_marker = SnapMarkerItem()
            self._snap_marker.setVisible(False)
            sc.addItem(self._snap_marker)

        if sc.items():
            sc.setSceneRect(sc.itemsBoundingRect().adjusted(-20, -20, 20, 20))
            self.view.fitInView(sc.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._update_state()
        self._update_snap_state()

    def _update_state(self):
        if not self.result_plan.image_path:
            self.lbl_state.setText("Aucun plan de cale : le placement des "
                                   "palettes se fera sur fond neutre.")
            return
        n = len(self.result_plan.cal_points)
        if not self.result_plan.calibration.valid:
            self.lbl_state.setText(
                f"Image importée · {n} point(s) de calage — il en faut au "
                "moins 2, décalés horizontalement et verticalement.")
            return
        errs = self.result_plan.calibration.residuals(
            [p["pixel"] for p in self.result_plan.cal_points],
            [p["real"] for p in self.result_plan.cal_points])
        pire = max(errs) if errs else 0.0
        self.lbl_state.setText(
            f"Plan calé · {n} point(s) · écart résiduel maximal {pire:.3f} m. "
            "Vérifiez que le contour orange tombe sur le dessin de la cale.")

    def values(self):
        """Le Calibrated à affecter à la capacité, ou None pour « pas de plan »."""
        if self._removed or not self.result_plan.image_path:
            return None
        return self.result_plan
