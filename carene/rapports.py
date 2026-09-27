# -*- coding: utf-8 -*-
"""Exports et rapports : ce que l'écran dit, sur papier.

Tout part de la fenêtre principale (`MainWindow`) et de ce qu'elle a déjà
calculé et affiché : `win._last = (poids, eq, gz, rep)`, les lignes de
`_details_flottaison`, le texte de `_reserves`, le bilan de `bilan.construire`,
les agrégats du tableau des capacités. **Rien n'est recalculé ici** : un
rapport qui referait le calcul à sa manière finirait un jour par contredire
l'écran, et c'est l'écran que l'officier a validé.

Trois règles, communes à tous les documents :

- chaque page porte un **en-tête** (navire, point du journal — numéro, date,
  lieu, libellé — version de Carène) et un **pied** avec `MENTION` et
  `AVERTISSEMENT` : un feuillet détaché d'un rapport reste identifiable, et
  reste marqué « aide, ni certifié ni réglementaire » ;
- **rien d'extrapolé sans sa réserve** : les messages du moteur, la gîte
  permanente, l'angle d'envahissement approché sont repris tels quels ; si
  l'équilibre est hors du domaine des tables (`win._fiable` faux), la
  première page du rapport le dit dans un encadré, avant tout chiffre ;
- lisible en **noir et blanc** : les verdicts sont écrits en toutes lettres,
  la couleur n'est qu'un renfort.

Techniquement : HTML construit en Python, mis en page par `QTextDocument`,
paginé à la main sur un `QPdfWriter` (PDF) ou un `QPrinter` (impression) pour
pouvoir dessiner l'en-tête et le pied sur **chaque** page — `print_()` ne le
permet pas. Les CSV sont en UTF-8 avec BOM, séparateur « ; », virgule
décimale : c'est ce qu'Excel en français ouvre d'un double-clic.

Pas de widget ici, à deux exceptions près, rendues hors écran : la vue de
profil et le plan de pont, qu'on dessine dans une image plutôt que de
réécrire leur peinture (D-10 : ce qui est montré est ce qui est calculé).
"""
from __future__ import annotations

import csv
import datetime as _dt
import html as _html
import math
import os
import unicodedata

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt, QUrl
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QPen,
    QTextDocument,
)

from . import AVERTISSEMENT, MENTION, __version__, app_paths
from . import bilan as _bilan
from .core.criteria import format_nombre
from . import ports as _ports
from .core.tirants_releves import NOM_POIDS as NOM_POIDS_TIRANTS

# ---------------------------------------------------------------- couleurs
# Couleurs d'impression : elles ne viennent pas du thème (un rapport ne
# s'imprime pas en sombre) et sont choisies pour rester distinctes en gris.
C_OK, C_OK_FOND = "#1B6E3A", "#E3F2E7"
C_KO, C_KO_FOND = "#A8231B", "#FBE4E1"
C_NA, C_NA_FOND = "#5A5F66", "#ECEEF1"
C_ENTETE_FOND = "#E5EAF0"
C_GROUPE_FOND = "#F2F4F7"
C_TRAIT = "#8A939E"
C_COURBE = "#1F4E79"

# Les exports proposés, dans l'ordre du dossier (A_FAIRE « Exports et
# rapports ») : clé interne → libellé de la case à cocher.
EXPORTS = [
    ("rapport", "Rapport de stabilité (PDF)"),
    ("capacites", "Relevé des capacités (CSV + PDF)"),
    ("chargement", "Chargement : manifeste et charges posées (CSV + PDF)"),
    ("plan", "Plan de chargement, un pont par page (PDF)"),
    ("plans_cotes", "Plans cotés des cales, à vérifier à bord (PDF A3)"),
    ("pointage", "Feuilles de pointage, chargement et déchargement (PDF)"),
    ("journal", "Journal des points (CSV)"),
]
# LE PLAN DES DOCKERS EST À PART, et ce n'est pas un oubli. Les documents
# ci-dessus forment le lot de l'escale : ils partent ensemble dans le dossier
# du point, et ils portent tous le nom de fichier de la maison
# (`Contexte.nom_fichier`). La planche du quai, elle, se tire à la demande,
# se nomme par ce qu'elle est (`plan_dockers.nom_fichier`) et change de
# mains : elle a sa case dans la fenêtre Exporter…, mais `tout_exporter(win,
# dossier)` sans liste de choix continue d'écrire le lot de l'escale, et lui
# seul.
EXPORT_DOCKERS = ("plan_dockers", "Plan de chargement pour les dockers (PDF)")
DOSSIER_EXPORTS = "exports"


# ================================================================ contexte
class Contexte:
    """Ce que tous les documents ont en commun : l'identité du navire et du
    point, le dernier calcul tel qu'affiché, et ses réserves."""

    def __init__(self, win):
        self.win = win
        folder = app_paths.ship_folder()
        self.dossier_navire = folder
        self.navire = (app_paths.ship_name(folder)
                       or getattr(win.project, "ship_name", "") or "Navire")
        nav = getattr(win, "nav", None)
        self.nav = nav
        self.identification = dict((getattr(nav, "manifest", None) or {})
                                   .get("identification", {}) or {})
        self.point = win.point
        # Les escales du navire : elles donnent le code à mettre à côté du nom
        # (« FRLEH — Le Havre ») et l'orthographe de référence — deux façons
        # d'écrire le même port ne doivent pas sortir deux feuilles de pointage.
        self.escales = _ports.liste_du_bord(win)
        self.genere = _dt.datetime.now().strftime("%d/%m/%Y %H:%M")
        self.version = __version__
        last = getattr(win, "_last", None)
        self.poids = self.eq = self.gz = self.rep = None
        self.flottaison = []
        self.reserves = []
        self.bilan = None
        self.totaux = None
        self.fiable = bool(getattr(win, "_fiable", True))
        # le message du panneau Résultats quand le calcul est hors domaine ou
        # impossible : c'est lui, et pas une reformulation, qui est repris
        self.message_domaine = ""
        lbl = getattr(getattr(win, "results_panel", None), "lbl_none", None)
        # isHidden(), pas isVisible() : hors écran, rien n'est « visible »
        if lbl is not None and (not lbl.isHidden() or not last):
            self.message_domaine = lbl.text()
        # La voilure portée au point : elle décide du critère de vent
        # appliqué, donc du verdict — un rapport qui ne la dit pas laisse
        # croire que les critères valent quelle que soit la toile dehors.
        self.voilure = ""
        self.voilure_detail = ""
        if nav is not None:
            profils = getattr(nav, "profils_vent", None)
            if profils:
                pid = profils.resoudre(getattr(win.condition, "voilure", None))
                if pid:
                    self.voilure = profils.nom(pid)
                    self.voilure_detail = profils.description(pid)
        if nav is not None:
            self.bilan = _bilan.construire(win.condition, nav, win.project)
            try:
                self.totaux = win.condition.to_core(nav, win.project).totals()
            except Exception:
                self.totaux = None
        if last:
            self.poids, self.eq, self.gz, self.rep = last
            if self.totaux is not None:
                _p, lcg, tcg, vcg, fsm = self.totaux
                self.flottaison = list(win._details_flottaison(
                    self.poids, lcg, tcg, vcg, fsm, self.eq, self.gz))
            texte = win._reserves(self.gz, self.rep)
            self.reserves = [t[2:] if t.startswith("• ") else t
                             for t in texte.split("<br>") if t.strip()]
        self.theta_f = getattr(win, "_theta_f", None)
        self.gite = getattr(win, "_gite", None)
        self.verdict = getattr(getattr(win, "pill_verdict", None), "text",
                               lambda: "—")()

    # ------------------------------------------------------------ libellés
    @property
    def point_texte(self):
        p = self.point
        parts = [f"Point {p.numero}", p.date_lisible]
        if p.lieu:
            parts.append(p.lieu)
        if p.libelle:
            parts.append(p.libelle)
        parts.append(p.etat)
        return " · ".join(parts)

    def nom_fichier(self, suffixe, ext):
        """« MON_NAVIRE_point0003_2026-09-05_rapport.pdf » : le navire, le point
        et la date dans le nom — les fichiers se retrouvent hors du logiciel."""
        date = (self.point.horodatage or "")[:10] or _dt.date.today().isoformat()
        return f"{_sur(self.navire)}_point{self.point.numero:04d}_{date}_{suffixe}.{ext}"

    def dossier_par_defaut(self):
        return os.path.join(self.dossier_navire, DOSSIER_EXPORTS,
                            f"point_{self.point.numero:04d}")


def _port(ctx, nom):
    """Un port tel qu'il s'écrit dans un document : « FRLEH — Le Havre ».

    Le code vient de la liste des escales du navire, jamais de la liste
    mondiale : deux ports du monde portent le même nom, et un code qu'on
    n'aurait pas choisi serait un chiffre inventé sur un papier signé. Une
    escale que la liste ne connaît pas s'écrit telle qu'elle a été tapée."""
    return _ports.etiquette_de(getattr(ctx, "escales", None), nom)


def _sur(nom):
    """Un nom de fichier sans accent ni séparateur : lisible sur toute clé USB."""
    s = unicodedata.normalize("NFKD", str(nom or "")).encode("ascii", "ignore").decode()
    s = "".join(c if (c.isalnum() or c in "-_") else "_" for c in s.strip())
    while "__" in s:
        s = s.replace("__", "_")
    return s.strip("_") or "navire"


def e(texte):
    """Échappement HTML de ce qui vient des saisies."""
    # quote=False : les apostrophes restent lisibles dans le HTML (et le texte
    # de l'avertissement s'y retrouve tel quel)
    return _html.escape(str(texte if texte is not None else ""), quote=False)


# ================================================================ CSV
def _nb(v, nd=2, signe=False):
    """Nombre au format français (virgule décimale) pour Excel."""
    if v is None or v == "":
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f != f:
        return ""
    s = f"{f:+.{nd}f}" if signe else f"{f:.{nd}f}"
    return s.replace(".", ",")


def ecrire_csv(chemin, lignes):
    """UTF-8 avec BOM, « ; » : Excel en français l'ouvre sans assistant."""
    os.makedirs(os.path.dirname(chemin) or ".", exist_ok=True)
    with open(chemin, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        for l in lignes:
            w.writerow(["" if v is None else v for v in l])
    return chemin


def _entete_csv(ctx, titre):
    """Les premières lignes de tout CSV : d'où il vient, ce qu'il vaut."""
    return [[titre], [f"Navire : {ctx.navire}"], [ctx.point_texte],
            [f"Généré le {ctx.genere} — {MENTION}"], [AVERTISSEMENT], []]


# ================================================================ HTML
_STYLE = """
<style>
h1 { font-size: 15pt; margin: 0 0 2px 0; }
h2 { font-size: 11.5pt; margin: 14px 0 4px 0; color: #1F2A36; }
p  { margin: 2px 0 4px 0; }
td, th { font-size: 8.5pt; }
th { background-color: %(entete)s; text-align: left; }
.d  { color: #4E5761; }
.num { text-align: right; }
</style>
""" % {"entete": C_ENTETE_FOND}


def _table(entetes, lignes, largeurs=None, num=()):
    """Un tableau HTML simple ; `lignes` sont des listes de cellules, chaque
    cellule étant un texte ou (texte, style)."""
    out = ['<table border="1" cellspacing="0" cellpadding="3" width="100%" '
           f'style="border-color:{C_TRAIT}; border-collapse:collapse;">']
    if entetes:
        # <thead> n'est pas décoratif : QTextDocument en fait une « ligne
        # d'en-tête » (headerRowCount) et la RÉPÈTE en haut de chaque page
        # quand le tableau est coupé. Sans lui, la deuxième page d'un
        # manifeste arrive sans titres de colonnes.
        out.append("<thead><tr>")
        for i, h in enumerate(entetes):
            w = f' width="{largeurs[i]}"' if largeurs and largeurs[i] else ""
            al = ' align="right"' if i in num else ""
            out.append(f"<th{w}{al}>{e(h)}</th>")
        out.append("</tr></thead>")
    for ligne in lignes:
        cells = []
        for i, c in enumerate(ligne):
            style = ""
            attrs = ""
            if isinstance(c, tuple):
                c, style = c[0], c[1]
            if isinstance(c, dict):
                # une cellule « toute faite » (HTML, colspan, fond) : elle
                # garde son alignement, même dans une colonne de nombres
                attrs = " " + c.get("attrs", "")
                style = c.get("style", "")
                c = c.get("texte", "")
                al = ""
            else:
                al = ' align="right"' if i in num else ""
            st = f' style="{style}"' if style else ""
            # un dict porte du HTML déjà formé ; une chaîne est TOUJOURS
            # échappée — un nom de poids divers « <Bossoir> & grue » sortait
            # vide, pris pour du HTML (RS-4, D-78)
            brut = c if attrs else e(c)
            cells.append(f"<td{al}{st}{attrs}>{brut}</td>")
        out.append("<tr>" + "".join(cells) + "</tr>")
    out.append("</table>")
    return "\n".join(out)


def _ligne_groupe(texte, ncols, fond=C_GROUPE_FOND):
    return [{"texte": f"<b>{e(texte)}</b>",
             "attrs": f'colspan="{ncols}" bgcolor="{fond}"'}]


def _cadre(texte, fond, bord, titre=""):
    """Un encadré pleine largeur : le seul moyen sûr d'avoir une boîte colorée
    dans QTextDocument est un tableau d'une cellule."""
    t = f"<b>{e(titre)}</b><br>" if titre else ""
    return (f'<table width="100%" cellpadding="6" cellspacing="0" border="2" '
            f'style="border-color:{bord};" bgcolor="{fond}"><tr><td>{t}{texte}'
            "</td></tr></table>")


def _identification_html(ctx, titre, complet=True):
    """Le cartouche de première page. Complet pour le rapport (identité du
    navire, du point, du document) ; réduit à une ligne pour les listes, où
    la place est au tableau et où l'en-tête de page dit déjà l'essentiel."""
    ident = ctx.identification
    p = ctx.point
    if not complet:
        return (f"<h1>{e(titre)}</h1><p class='d'>{e(ctx.navire)} — {e(ctx.point_texte)}"
                f" — généré le {e(ctx.genere)}, {e(MENTION)}</p>")
    lignes = [("Navire", ctx.navire)]
    for cle, lib in (("type", "Type"), ("armateur", "Armateur"), ("imo", "N° IMO"),
                     ("pavillon", "Pavillon"), ("societe_classification", "Classification")):
        if ident.get(cle):
            lignes.append((lib, str(ident[cle])))
    lignes += [("Point du journal", f"Point {p.numero} — {p.etat}"),
               ("Date", p.date_lisible), ("Lieu", _port(ctx, p.lieu) or "—"),
               ("Libellé", p.libelle or "—")]
    if p.note:
        lignes.append(("Note", p.note))
    lignes += [("Document généré le", ctx.genere), ("Logiciel", MENTION)]
    rows = [[(lib, "color:#4E5761"), val] for lib, val in lignes]
    return f"<h1>{e(titre)}</h1><p class='d'>{e(ctx.navire)} — {e(ctx.point_texte)}</p>" \
        + _table([], rows, largeurs=["28%", None])


def _avertissements_html(ctx):
    """L'encadré de première page : ce qui limite la portée du document. En
    rouge si le calcul est hors domaine (rien de ce qui suit n'est
    réglementaire), en gris sinon — mais toujours présent."""
    corps = e(AVERTISSEMENT)
    if not ctx.fiable and ctx.message_domaine:
        return _cadre(f"{corps}<br><br><b>{e(ctx.message_domaine)}</b><br>"
                      "Les valeurs de ce rapport sont <b>hors du domaine des "
                      "tables</b> du dossier : elles sont extrapolées et n'ont "
                      "aucune valeur réglementaire.",
                      C_KO_FOND, C_KO, "CALCUL HORS DOMAINE — VERDICT : "
                      + ctx.verdict)
    if ctx.eq is None:
        return _cadre(f"{corps}<br><br><b>Aucun résultat de calcul pour ce point"
                      f"{' : ' + e(ctx.message_domaine) if ctx.message_domaine else '.'}"
                      "</b>", C_NA_FOND, C_NA, "PAS DE CALCUL")
    return _cadre(corps, C_NA_FOND, C_TRAIT, "Avertissement")


# ================================================================ images
def image_gz(ctx, largeur=1400, hauteur=700):
    """La courbe GZ, redessinée pour l'impression.

    C'est la courbe **résiduelle** du moteur (`gz.heel_residuel_deg`,
    `gz.gz_residuel_m`) : celle que les critères intègrent, mesurée depuis la
    gîte d'équilibre et du côté où le navire est couché. Sur un navire droit
    elle est identique à la courbe de l'écran ; avec une bande, l'écran montre
    la courbe depuis la verticale et le rapport dit d'où partent ses angles.
    Fond blanc, repères 30°, 40° et θf, GZmax annoté en clair."""
    img = QImage(largeur, hauteur, QImage.Format.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    gz = ctx.gz
    police = QFont("Sans Serif", 18)
    petite = QFont("Sans Serif", 15)
    p.setFont(police)
    if gz is None or not gz.heel_deg:
        p.setPen(QColor(C_NA))
        p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, "Pas de courbe GZ : aucun calcul.")
        p.end()
        return img
    o = gz.origine_deg
    residuelle = bool(gz.heel_residuel_deg) and len(gz.heel_residuel_deg) >= 2
    if residuelle:
        heels, gzs = list(gz.heel_residuel_deg), list(gz.gz_residuel_m)
        # θf est compté depuis la verticale : ramené à l'origine de la courbe
        theta_f = (float(ctx.theta_f) - abs(o or 0.0)) if ctx.theta_f is not None else None
    else:
        heels = [h for h in gz.heel_deg if h >= 0]
        gzs = gz.gz_m[-len(heels):]
        theta_f = float(ctx.theta_f) if ctx.theta_f is not None else None
    pad_l, pad_r, pad_t, pad_b = 110, 40, 60, 80
    w, h = largeur - pad_l - pad_r, hauteur - pad_t - pad_b
    x_max = max(60.0, max(heels))
    y_max = max(0.3, max(gzs) * 1.18)
    y_min = min(0.0, min(gzs) * 1.1)

    def px(a):
        return pad_l + a / x_max * w

    def py(g):
        return pad_t + h - (g - y_min) / (y_max - y_min) * h

    # grille
    p.setPen(QPen(QColor("#D5DAE0"), 1))
    step_x = 10 if x_max <= 65 else 20
    xt = 0.0
    while xt <= x_max + 1e-6:
        p.drawLine(int(px(xt)), pad_t, int(px(xt)), pad_t + h)
        xt += step_x
    step_y = 0.2 if y_max <= 1.4 else (0.5 if y_max <= 3.5 else 1.0)
    yt = math.ceil(y_min / step_y) * step_y
    while yt <= y_max + 1e-6:
        p.drawLine(pad_l, int(py(yt)), pad_l + w, int(py(yt)))
        yt += step_y
    # axes et graduations
    p.setPen(QPen(QColor("#333333"), 2))
    p.drawLine(pad_l, int(py(0)), pad_l + w, int(py(0)))
    p.drawLine(pad_l, pad_t, pad_l, pad_t + h)
    p.setPen(QColor("#333333"))
    p.setFont(petite)
    xt = 0.0
    while xt <= x_max + 1e-6:
        p.drawText(int(px(xt)) - 40, pad_t + h + 8, 80, 30,
                   Qt.AlignmentFlag.AlignCenter, f"{xt:g}°")
        xt += step_x
    yt = math.ceil(y_min / step_y) * step_y
    while yt <= y_max + 1e-6:
        p.drawText(0, int(py(yt)) - 15, pad_l - 10, 30,
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{yt:.1f}")
        yt += step_y
    if residuelle and o is not None and abs(o) > 0.05:
        legende = (f"Gîte depuis la position d'équilibre {o:+.1f}° (°), "
                   "du côté où le navire est couché — stabilité résiduelle")
    else:
        legende = "Gîte (°)"
    p.drawText(pad_l, hauteur - 34, w, 30, Qt.AlignmentFlag.AlignCenter, legende)
    p.save()
    p.translate(28, pad_t + h / 2)
    p.rotate(-90)
    p.drawText(-200, -15, 400, 30, Qt.AlignmentFlag.AlignCenter, "GZ (m)")
    p.restore()

    # repères : 30°, 40° (bornes des aires), θf
    def repere(angle, libelle, couleur, y_texte):
        if angle is None or angle <= 0 or angle > x_max:
            return
        stylo = QPen(QColor(couleur), 2)
        stylo.setStyle(Qt.PenStyle.DashLine)
        p.setPen(stylo)
        p.drawLine(int(px(angle)), pad_t, int(px(angle)), pad_t + h)
        p.setPen(QColor(couleur))
        r = QRectF(px(angle) + 6, pad_t + y_texte - 22, 420, 30)
        if r.right() > largeur - 6:          # étiquette à gauche du trait
            r = QRectF(px(angle) - 426, pad_t + y_texte - 22, 420, 30)
            p.drawText(r, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, libelle)
        else:
            p.drawText(r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, libelle)

    repere(30.0, "30°", "#8A939E", 24)
    repere(40.0, "40°", "#8A939E", 24)
    if theta_f is not None:
        depuis = (" depuis l'équilibre" if residuelle and abs(o or 0.0) >= 0.05 else "")
        repere(theta_f, f"θf ≈ {theta_f:.1f}°{depuis} (approché)", C_KO, 84)
    # courbe
    p.setPen(QPen(QColor(C_COURBE), 4))
    pts = [(px(a), py(g)) for a, g in zip(heels, gzs)]
    for i in range(len(pts) - 1):
        p.drawLine(int(pts[i][0]), int(pts[i][1]), int(pts[i + 1][0]), int(pts[i + 1][1]))
    # le sommet : GZmax, sur la courbe résiduelle comme dans le tableau
    if residuelle and gz.gz_max_m is not None and gz.angle_gz_max_deg is not None:
        cx, cy = px(gz.angle_gz_max_deg), py(gz.gz_max_m)
        p.setBrush(QColor(C_COURBE))
        p.setPen(QPen(QColor("#FFFFFF"), 2))
        p.drawEllipse(int(cx) - 8, int(cy) - 8, 16, 16)
        p.setPen(QColor(C_COURBE))
        p.setFont(police)
        texte = f"GZmax {gz.gz_max_m:.3f} m à {gz.angle_gz_max_deg:.1f}°"
        r = QRectF(cx + 14, max(pad_t, cy - 40), 520, 30)
        if r.right() > largeur - 6:
            r = QRectF(cx - 534, max(pad_t, cy - 40), 520, 30)
            p.drawText(r, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, texte)
        else:
            p.drawText(r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, texte)
    p.end()
    return img


def image_profil(win, largeur=1000, hauteur=340):
    """Le profil et la coupe au maître de la vue Stabilité, tels qu'à l'écran :
    une instance hors écran de la même vue, dessinée dans une image.

    Plus grande que la vue de l'écran (D-59) : à 820 × 280 px, la ligne de
    légende du haut passait sous le titre « PROFIL — Δ … t » et se lisait
    tronquée sur le papier. Les proportions sont celles de la vue, la figure
    occupe la même largeur de page — c'est sa définition qui change."""
    try:
        from .profil_view import ProfilView
        v = ProfilView(win)
        v.resize(largeur, hauteur)
        return v.grab().toImage()
    except Exception:            # pragma: no cover - la vue ne bloque jamais
        return None


def image_plan(win, deck, largeur=1600, hauteur=None):
    """Le plan d'un pont, tel que le peint la vue Chargement, sans le repère
    de coupe (il n'a de sens que devant la coupe interactive). L'image prend
    les proportions des cales du pont : un pont de 60 m sur 12 ne se rend pas
    dans un carré."""
    from .cargo_panel import DeckStowView
    from .project import KIND_CONTOUR

    class _PlanImprimable(DeckStowView):
        def x_coupe_effectif(self):
            return None          # pas de trait rouge sur le papier

    if hauteur is None:
        pts = [p for c in deck.capacities
               if c.kind != KIND_CONTOUR and len(c.points) >= 3 for p in c.points]
        if pts:
            sx = max(p[0] for p in pts) - min(p[0] for p in pts)
            sy = max(p[1] for p in pts) - min(p[1] for p in pts)
            hauteur = int((largeur - 60) * sy / sx + 60) if sx > 0 else 1000
        else:
            hauteur = 1000
        hauteur = max(380, min(1000, hauteur))
    v = _PlanImprimable(win)
    v.deck = deck
    v.mode_couleur = "lot"
    v.resize(largeur, hauteur)
    return v.grab().toImage()


def image_case(cote=14):
    """La case à cocher des feuilles de pointage : une image, parce qu'un
    caractère ☐ dépend de la police disponible à l'impression."""
    img = QImage(cote, cote, QImage.Format.Format_ARGB32)
    img.fill(QColor("#FFFFFF"))
    p = QPainter(img)
    p.setPen(QPen(QColor("#000000"), 1))
    p.drawRect(0, 0, cote - 1, cote - 1)
    p.end()
    return img


# ================================================================ mise en page
class _Page:
    """Les dimensions utiles d'un périphérique paginé, en pixels de ce
    périphérique. `k` convertit une taille pensée à 96 dpi (écran)."""

    def __init__(self, device):
        self.device = device
        self.dpi = float(device.resolution())
        self.k = self.dpi / 96.0
        rect = device.pageLayout().paintRectPixels(int(self.dpi))
        self.largeur = rect.width()
        self.hauteur = rect.height()

    def px(self, n):
        return int(round(n * self.k))


def _preparer(device, paysage=False, titre=""):
    """Réglages communs PDF / imprimante : A4, marges 15 mm."""
    device.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    device.setPageOrientation(QPageLayout.Orientation.Landscape if paysage
                              else QPageLayout.Orientation.Portrait)
    device.setPageMargins(QMarginsF(15, 14, 15, 12), QPageLayout.Unit.Millimeter)
    if isinstance(device, QPdfWriter):
        device.setResolution(96)
        device.setTitle(titre)
        device.setCreator(MENTION)


def peindre(device, ctx, titre, construire_html, ressources=None):
    """Pagine un document sur `device` avec en-tête et pied sur chaque page.

    `construire_html(page)` reçoit les dimensions utiles (largeur en pixels du
    périphérique, facteur `k`) et rend le HTML du corps ; `ressources` est un
    dict nom → QImage référencé par les balises <img>. Renvoie le nombre de
    pages."""
    page = _Page(device)
    painter = QPainter(device)
    if not painter.isActive():
        # le fichier n'a pas pu être ouvert en écriture (encore ouvert dans
        # un lecteur PDF, dossier en lecture seule) : l'ancien fichier était
        # laissé en place et l'export annoncé « écrit » (RS-1, D-78)
        raise OSError("le PDF ne peut pas être écrit — est-il encore ouvert dans "
                      "un lecteur, ou le dossier est-il en lecture seule ?")
    try:
        # en-tête et pied : mesurés d'abord, pour savoir ce qui reste au corps
        f_ent = QFont("Sans Serif", 8)
        f_pied = QFont("Sans Serif", 7)
        painter.setFont(f_pied)
        h_ligne = painter.fontMetrics().lineSpacing()
        rect_avert = painter.boundingRect(QRectF(0, 0, page.largeur, 10000),
                                          int(Qt.TextFlag.TextWordWrap), AVERTISSEMENT)
        h_pied = int(rect_avert.height() + 2 * h_ligne + page.px(10))
        painter.setFont(f_ent)
        h_ent = int(painter.fontMetrics().lineSpacing() * 2 + page.px(8))
        y_corps = h_ent
        h_corps = page.hauteur - h_ent - h_pied
        if h_corps < page.px(100):
            h_corps = page.hauteur - h_ent
        page.hauteur_corps = h_corps       # le plan de pont s'y adapte

        doc = QTextDocument()
        doc.documentLayout().setPaintDevice(device)
        doc.setDefaultFont(QFont("Sans Serif", 9))
        doc.setDocumentMargin(0)
        for nom, img in (ressources or {}).items():
            doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(nom), img)
        doc.setHtml(construire_html(page))
        doc.setPageSize(QSizeF(page.largeur, h_corps))
        n = max(1, doc.pageCount())
        for i in range(n):
            if i > 0:
                device.newPage()
            painter.save()
            painter.translate(0, y_corps - i * h_corps)
            painter.setClipRect(QRectF(0, i * h_corps, page.largeur, h_corps))
            doc.drawContents(painter, QRectF(0, i * h_corps, page.largeur, h_corps))
            painter.restore()
            _entete_pied(painter, page, ctx, titre, i + 1, n, f_ent, f_pied, h_ent, h_pied)
        return n
    finally:
        painter.end()


def _entete_pied(painter, page, ctx, titre, i, n, f_ent, f_pied, h_ent, h_pied):
    painter.save()
    painter.setFont(f_ent)
    painter.setPen(QColor("#1F2A36"))
    lh = painter.fontMetrics().lineSpacing()
    gauche = QRectF(0, 0, page.largeur * 0.55, lh)
    droite = QRectF(page.largeur * 0.45, 0, page.largeur * 0.55, lh)
    painter.drawText(gauche, Qt.AlignmentFlag.AlignLeft, f"Carène — {titre}")
    painter.drawText(droite, Qt.AlignmentFlag.AlignRight, ctx.navire)
    painter.setPen(QColor("#4E5761"))
    painter.drawText(QRectF(0, lh, page.largeur * 0.7, lh), Qt.AlignmentFlag.AlignLeft,
                     ctx.point_texte)
    painter.drawText(QRectF(page.largeur * 0.6, lh, page.largeur * 0.4, lh),
                     Qt.AlignmentFlag.AlignRight, f"Carène {ctx.version}")
    painter.setPen(QPen(QColor(C_TRAIT), max(1, page.px(1))))
    painter.drawLine(0, h_ent - page.px(3), page.largeur, h_ent - page.px(3))
    # pied
    y0 = page.hauteur - h_pied
    painter.drawLine(0, y0 + page.px(3), page.largeur, y0 + page.px(3))
    painter.setFont(f_pied)
    fm = painter.fontMetrics()
    lh = fm.lineSpacing()
    y = y0 + page.px(6)
    painter.setPen(QColor("#1F2A36"))
    painter.drawText(QRectF(0, y, page.largeur * 0.7, lh), Qt.AlignmentFlag.AlignLeft, MENTION)
    painter.drawText(QRectF(page.largeur * 0.7, y, page.largeur * 0.3, lh),
                     Qt.AlignmentFlag.AlignRight, f"page {i} / {n}")
    y += lh
    painter.setPen(QColor("#4E5761"))
    painter.drawText(QRectF(0, y, page.largeur, h_pied - lh),
                     Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, AVERTISSEMENT)
    painter.restore()


def ecrire_pdf(chemin, ctx, titre, construire_html, ressources=None, paysage=False):
    os.makedirs(os.path.dirname(chemin) or ".", exist_ok=True)
    writer = QPdfWriter(chemin)
    _preparer(writer, paysage, f"{titre} — {ctx.navire}")
    peindre(writer, ctx, titre, construire_html, ressources)
    return chemin


# ================================================================ 1. rapport
# =================================================== le dossier, en détail
# Le bord, 22/09/2026 : « l'export du dossier de stabilité paraît bien maigre.
# On n'a aucun détail des capacités par exemple. Il faudrait le résultat pour
# tous les cas (voile et non voile). Un dossier bien exhaustif qui montre plus
# que juste le réglementaire. » (D-59)
#
# Les fonctions qui suivent NE CALCULENT PAS de stabilité : elles relisent ce
# que le moteur a déjà produit pour ce point (`eq.hydro`, la courbe GZ, les
# tables du dossier) et le mettent en tableau. La seule exception est le
# comparatif des voilures, qui redemande à la fenêtre le critère de vent de
# chaque configuration — le même code que le sélecteur de l'écran, sur le
# même équilibre et la même courbe (voir `MainWindow.rapport_de_vent`).

# Les colonnes de la table hydrostatique, en clair et avec leur unité. Une
# colonne que le dossier porte sans figurer ici s'imprime sous son nom brut :
# un dossier étranger ne perd rien de ce qu'il a.
LIBELLES_HYDRO = {
    "Deplacement_t": ("Déplacement", "t", 2),
    "Volume_m3": ("Volume de carène", "m³", 2),
    "LCB_m": ("LCB — centre de carène longitudinal", "m", 3),
    "VCB_m": ("VCB — centre de carène vertical", "m", 3),
    "KMt_m": ("KMt — métacentre transversal", "m", 3),
    "KMl_m": ("KMl — métacentre longitudinal", "m", 2),
    "LCF_m": ("LCF — centre de flottaison", "m", 3),
    "WPA_m2": ("Aire de flottaison", "m²", 2),
    "TPC_t_cm": ("TPC — tonnes par centimètre d'immersion", "t/cm", 3),
    "MCT_tm_cm": ("MCT — moment pour 1 cm d'assiette", "t·m/cm", 2),
    "BMT_m": ("BMt — rayon métacentrique transversal", "m", 3),
    "BML_m": ("BMl — rayon métacentrique longitudinal", "m", 2),
    "Inertie_T_m4": ("Inertie transversale de flottaison", "m⁴", 1),
    "Inertie_L_m4": ("Inertie longitudinale de flottaison", "m⁴", 1),
    "WSA_m2": ("Surface mouillée", "m²", 2),
    "TE_AR_m": ("Tirant d'eau arrière (perpendiculaire)", "m", 3),
    "TE_AV_m": ("Tirant d'eau avant (perpendiculaire)", "m", 3),
}


def _releve_du_point(ctx):
    """(Releve, Ecart, corrigé ?) du relevé attaché au point, ou None.

    L'écart est RECALCULÉ ici, sur le chargement déclaré du rapport : un
    relevé archivé avec un chargement qu'on a modifié depuis ne doit pas
    imprimer l'écart d'hier."""
    cond = getattr(ctx.win, "condition", None)
    brut = getattr(cond, "tirants_releves", None)
    if not brut or ctx.nav is None or ctx.totaux is None:
        return None
    try:
        from .core import tirants_releves as _tr
        r = _tr.Releve.from_dict(brut)
        # le chargement DÉCLARÉ, poids fictif exclu : c'est lui que la coque
        # met à l'épreuve, et c'est la même règle que la fenêtre de relevé —
        # les deux diraient sinon deux écarts différents du même relevé
        poids, lcg = float(ctx.totaux[0]), float(ctx.totaux[1])
        fictifs = [e for e in cond.extras
                   if str(getattr(e, "nom", "")).startswith(NOM_POIDS_TIRANTS)]
        w = sum(e.poids_t for e in fictifs)
        if abs(w) > 1e-9 and abs(poids - w) > 1e-9:
            m = poids * lcg - sum(e.poids_t * e.lcg_m for e in fictifs)
            poids, lcg = poids - w, m / (poids - w)
        return r, _tr.comparer(ctx.nav, r, poids, lcg), bool(fictifs)
    except Exception:                      # pragma: no cover - jamais bloquant
        return None


def _lignes_hydro(ctx):
    """La ligne hydrostatique du point, colonne par colonne — TELLE QUE LUE
    par le moteur (`eq.hydro`), pas relue ni réinterpolée ici."""
    eq = ctx.eq
    h = dict(getattr(eq, "hydro", None) or {}) if eq is not None else {}
    # l'ordre du tableau est celui de LIBELLES_HYDRO (du déplacement aux
    # inerties) ; une colonne que le dossier porte en plus vient ensuite,
    # sous son nom brut — un dossier étranger ne perd rien
    connues = [c for c in LIBELLES_HYDRO if c in h]
    autres = [c for c in h if c not in LIBELLES_HYDRO]
    out = []
    for col in connues + sorted(autres):
        if col in ("TE_milieu_m", "Assiette_m"):
            continue                      # déjà en tête du rapport
        lib, unite, nd = LIBELLES_HYDRO.get(col, (col, "", 3))
        try:
            v = float(h[col])
        except (TypeError, ValueError):
            continue
        out.append((lib, f"{v:,.{nd}f}".replace(",", " "), unite))
    return out


def _domaines_texte(ctx):
    """Les bornes des tables du dossier, écrites en toutes lettres : un
    chiffre juste au bord d'une table ne se lit pas comme un chiffre au
    milieu, et le rapport doit permettre de le voir sans ouvrir le CSV."""
    nav = ctx.nav
    eq = ctx.eq
    if nav is None or eq is None:
        return ""
    bouts = []
    hydro = getattr(nav, "hydro", None)
    if hydro is not None:
        (t0, t1), (d0, d1) = hydro.bounds(eq.trim_m)
        bouts.append(f"hydrostatiques : assiette {t0:+.2f} à {t1:+.2f} m, "
                     f"tirant d'eau {d0:.2f} à {d1:.2f} m à cette assiette")
    kn = getattr(nav, "kn", None)
    if kn is not None:
        (t0, t1), (w0, w1) = kn.bounds(eq.trim_m)
        angles = getattr(nav, "kn_heel_angles", []) or []
        bouts.append(f"pantocarènes : assiette {t0:+.2f} à {t1:+.2f} m, "
                     f"déplacement {w0:,.0f} à {w1:,.0f} t".replace(",", " ")
                     + (f", gîte 0 à {max(angles):g}°" if angles else ""))
    return " ; ".join(bouts)


def _lignes_gz(ctx, pas=5.0):
    """La courbe GZ en chiffres : angle, GZ, aire cumulée depuis l'équilibre.

    Les angles remarquables (GZmax, θf, annulation, 30°, 40°) sont insérés à
    leur place avec leur nom : ce sont eux que l'on cherche dans un dossier,
    et les lire sur un graphique n'est pas les lire."""
    from .core import stability
    gz = ctx.gz
    if gz is None or not gz.heel_residuel_deg:
        return []
    fin = float(gz.heel_residuel_deg[-1])
    theta_f = None
    if ctx.theta_f is not None:
        theta_f = float(ctx.theta_f) - abs(gz.origine_deg or 0.0)
    reperes = {}
    for angle, nom in ((gz.angle_gz_max_deg, "GZ max"),
                       (gz.angle_annulation_deg, "annulation du GZ"),
                       (theta_f, "envahissement θf"),
                       (30.0, "30°"), (40.0, "40°")):
        if angle is None or not (0 < float(angle) <= fin + 1e-9):
            continue
        reperes.setdefault(round(float(angle), 2), []).append(nom)
    angles = {0.0: []}
    a = pas
    while a <= fin + 1e-9:
        angles.setdefault(round(a, 2), [])
        a += pas
    for angle, noms in reperes.items():
        angles.setdefault(angle, [])
        angles[angle] = sorted(set(angles[angle] + noms))
    out = []
    from .core.interp import pchip_eval
    for angle in sorted(angles):
        val = float(pchip_eval(gz.heel_residuel_deg, gz.gz_residuel_m, [angle])[0])
        aire = stability.aire_residuelle(gz, 0.0, angle) if angle > 0 else 0.0
        absolu = (gz.origine_deg or 0.0) + (gz.sens or 1) * angle
        out.append({"angle": angle, "absolu": absolu, "gz": val,
                    "aire": aire, "repere": ", ".join(angles[angle])})
    return out


def _courbes_limites(ctx):
    """La marge aux courbes limites du dossier (KG max, GM min) au
    déplacement et à l'assiette du point, ou None si le dossier n'en porte
    pas. `kgmax_gmmin.csv` était chargé et n'était lu par personne : c'est
    pourtant la courbe que tout officier regarde en premier (D-59)."""
    nav, eq, gz = ctx.nav, ctx.eq, ctx.gz
    if nav is None or eq is None or gz is None:
        return None
    grille = getattr(nav, "kgmax", None)
    if grille is None:
        return None
    depl = float(eq.displacement_t)
    trim = float(eq.trim_m)
    dedans = bool(grille.contains(trim, depl))
    ligne = grille.row_at(trim, depl)
    kg_max = ligne.get("KG_max_m")
    gm_min = ligne.get("GM_min_m")
    # le critère limitant est un TEXTE du dossier : il ne s'interpole pas, on
    # cite celui de la ligne tabulée la plus proche, en disant laquelle
    critere, ligne_citee = "", None
    proche = None
    for r in getattr(nav, "kgmax_lignes", []) or []:
        try:
            d = (abs(float(r["Deplacement_t"]) - depl) / max(depl, 1.0)
                 + abs(float(r["Assiette_m"]) - trim))
        except (KeyError, TypeError, ValueError):
            continue
        if proche is None or d < proche:
            proche, ligne_citee = d, r
    if ligne_citee is not None:
        critere = (ligne_citee.get("Critere_limitant") or "").strip()
    return {
        "dedans": dedans,
        "kg_max_m": None if kg_max is None else float(kg_max),
        "gm_min_m": None if gm_min is None else float(gm_min),
        "kg_effectif_m": float(gz.kg_effectif_m),
        "gm_corrige_m": float(gz.gm_corrige_m),
        "deplacement_t": depl,
        "assiette_m": trim,
        "critere_limitant": critere,
        "ligne_citee": ligne_citee,
    }


def _cargaison_par_cale(ctx):
    """Par cale : ce qui y est posé, le poids, la charge au mètre carré et la
    charge admissible. Les colis sont comptés tels qu'ils sont posés — c'est
    le même `Hold` que le plan de chargement qui dit l'admissible sous chaque
    emprise, pas une règle réécrite ici."""
    from .cargo_panel import _hold_de
    win = ctx.win
    cond = win.condition
    lots = {m.lot_id: m for m in cond.manifeste}
    out = []
    for deck in win.project.sorted_decks():
        for cap in deck.capacities:
            places = list(cond.placements.get(cap.code) or [])
            if not places:
                continue
            hold = _hold_de(cap)
            poids = sum(pl.poids_total_t for pl in places)
            colis = sum(max(1, int(getattr(pl, "niveaux", 1) or 1)) for pl in places)
            aire = float(hold.aire_m2) if hold.aire_m2 else 0.0
            # la pile la plus chargée, et ce que le pont admet SOUS ELLE
            pire = None
            for pl in places:
                try:
                    charge = float(pl.charge_surfacique_t_m2())
                    lim = float(hold.charge_admissible_en(pl.rect))
                except Exception:          # une pose sans emprise exploitable
                    continue
                marge = (lim - charge) if lim > 0 else float("inf")
                if pire is None or marge < pire["marge"]:
                    pire = {"charge": charge, "limite": lim, "marge": marge,
                            "nom": pl.nom, "lot": (lots.get(pl.lot_id).nom
                                                   if lots.get(pl.lot_id) else "")}
            lcg = (sum(pl.poids_total_t * pl.x for pl in places) / poids) if poids > 0 else 0.0
            tcg = (sum(pl.poids_total_t * pl.y for pl in places) / poids) if poids > 0 else 0.0
            ports = sorted({(pl.port_dechargement or "") for pl in places} - {""})
            out.append({
                "pont": deck.name, "cale": cap.code, "nom": cap.name,
                "n_poses": len(places), "colis": colis, "poids_t": poids,
                "aire_m2": aire, "lcg_m": lcg, "tcg_m": tcg,
                "plancher_m": float(cap.z_min),
                "moyenne_t_m2": (poids / aire) if aire > 0 else None,
                "admissible_t_m2": float(getattr(cap, "charge_admissible_t_m2", 0.0) or 0.0),
                "pire": pire, "ports": ports,
            })
    return out


def _voilures_comparees(ctx):
    """Le point sous CHAQUE configuration de voilure du dossier.

    Même chargement, même équilibre, même courbe GZ : seule change la surface
    exposée au vent, donc le critère. C'est ce que l'écran afficherait si l'on
    déroulait le sélecteur de voilure, configuration par configuration — et
    c'est ce que le bord demandait : « le résultat pour tous les cas, voile et
    non voile ». La voilure portée au point est marquée.
    """
    win, nav = ctx.win, ctx.nav
    if nav is None or ctx.eq is None or ctx.gz is None:
        return []
    profils = getattr(nav, "profils_vent", None)
    if not profils or not hasattr(win, "rapport_de_vent"):
        return []
    porte = profils.resoudre(getattr(win.condition, "voilure", None))
    out = []
    for pid in list(profils.ids):
        try:
            titre, rep = win.rapport_de_vent(pid, ctx.eq, ctx.gz)
        except Exception as exc:           # une voilure que le dossier décrit mal
            out.append({"id": pid, "nom": profils.nom(pid), "titre": "",
                        "porte": pid == porte, "erreur": str(exc), "lignes": [],
                        "verdict": "NON ÉVALUABLE", "messages": []})
            continue
        if rep is None:
            continue
        vent, note = profils.surface_au_vent(pid, ctx.eq.draft_m)
        criteres = rep.criteres
        evaluables = [c for c in criteres if c.evaluable]
        if not criteres:
            verdict = "NON ÉVALUABLE"
        elif len(evaluables) < len(criteres):
            verdict = "INCOMPLET"
        else:
            verdict = "CONFORME" if rep.ok else "NON CONFORME"
        out.append({
            "id": pid, "nom": profils.nom(pid), "titre": titre,
            "porte": pid == porte, "erreur": "",
            "lignes": list(rep.checks), "verdict": verdict,
            "messages": list(rep.messages),
            "surface_m2": (vent or {}).get("Windage_area_m2"),
            "note": note,
        })
    return out


def _valeur_code(lignes, code, nd=1):
    """La valeur d'une ligne de critère, pour un tableau comparatif."""
    for c in lignes:
        if c.code == code:
            if not c.evaluable:
                return "—"
            return f"{c.valeur:,.{nd}f}".replace(",", " ")
    return "—"


def html_rapport(ctx, page, ressources):
    """Le dossier de stabilité du point, dans l'ordre du dossier approuvé.

    Douze sections, du poids embarqué au profil. Le bord (22/09/2026) le
    trouvait « bien maigre » : il n'avait ni le détail des capacités, ni la
    cargaison cale par cale, ni les hydrostatiques lues, ni la courbe GZ en
    chiffres, ni la marge aux courbes limites, ni les ouvertures — et il ne
    donnait le vent que dans la voilure portée. Tout cela y est (D-59), et
    rien n'y est recalculé : ce sont les chiffres de l'écran, mis en page.
    """
    out = [_STYLE, _identification_html(ctx, "Rapport de stabilité")]
    out.append("<p></p>" + _avertissements_html(ctx))

    # --- bilan des poids par groupe
    out.append("<h2>1. Bilan des poids</h2>")
    b = ctx.bilan
    if b is None:
        out.append("<p>Tables du navire absentes : pas de bilan.</p>")
    else:
        rows = []
        for g in b.groupes:
            rows.append(_ligne_groupe(g.nom.upper(), 7))
            for l in g.lignes:
                detail = l.detail + (f" — {l.alerte}" if l.alerte else "")
                rows.append([l.nom, f"{l.poids_t:.2f}", f"{l.lcg_m:.2f}", f"{l.tcg_m:+.2f}",
                             f"{l.vcg_m:.2f}", f"{l.fsm_tm:.1f}" if l.fsm_tm else "",
                             (detail, f"color:{C_KO if l.alerte and 'carène' not in l.alerte else '#4E5761'}")])
            if len(g.lignes) > 1:
                lcg, tcg, vcg = g.centres()
                rows.append([(f"Sous-total {g.nom.lower()}", "font-weight:bold"),
                             (f"{g.poids_t:.2f}", "font-weight:bold"), f"{lcg:.2f}", f"{tcg:+.2f}",
                             f"{vcg:.2f}", f"{g.fsm_tm:.1f}" if g.fsm_tm else "", ""])
        lcg, tcg, vcg = b.centres()
        gras = f"font-weight:bold; background-color:{C_ENTETE_FOND}"
        rows.append([("TOTAL", gras), (f"{b.poids_t:.2f}", gras), (f"{lcg:.3f}", gras),
                     (f"{tcg:+.3f}", gras), (f"{vcg:.3f}", gras),
                     (f"{b.fsm_tm:.1f}", gras), ("", gras)])
        out.append(_table(["Poste", "Poids t", "LCG m", "TCG m", "VCG m", "FSM t·m", "Détail"],
                          rows, largeurs=["26%", "9%", "9%", "9%", "9%", "9%", None],
                          num=(1, 2, 3, 4, 5)))
        conv = getattr(ctx.nav, "convention_fsm", "max")
        declaree = bool(str((getattr(ctx.nav, "manifest", None) or {})
                            .get("convention_fsm") or "").strip())
        du = "du dossier" if declaree else "appliquée par défaut (le dossier ne la déclare pas)"
        out.append(f"<p class='d'>Carène liquide : convention « {e(conv)} » {du} "
                   f"({'FSM maximal dès qu’une capacité est en carène liquide' if conv == 'max' else 'FSM interpolé au remplissage'}). "
                   "VCG solide ; la correction de carène liquide est portée une seule fois, sur le GM.</p>")

    # --- capacités, capacité par capacité
    out.append("<h2>2. Capacités liquides, capacité par capacité</h2>")
    lignes_cap = _lignes_capacites(ctx) if ctx.nav is not None else []
    if not lignes_cap:
        out.append("<p class='d'>Aucune capacité liquide au dossier de ce navire.</p>")
    else:
        # portrait : on retient les colonnes qui se lisent à bord (la sonde,
        # le volume, le remplissage, le poids et ses centres). Le relevé
        # complet, densité et note comprises, part en paysage dans son propre
        # export — celui-ci n'est pas là pour le remplacer mais pour que le
        # dossier se tienne tout seul.
        garde = [0, 1, 3, 4, 5, 6, 8, 9, 7, 10]
        entetes = [COLS_CAPACITES[i] for i in garde]
        trs = []
        for genre, vals in lignes_cap:
            cells = []
            for i in garde:
                nd = _ND_CAP[i]
                cells.append(_nb(vals[i], nd, signe=(i == 9)).replace(",", ".")
                             if nd else (vals[i] or ""))
            if genre == "groupe":
                st = f"font-weight:bold; background-color:{C_GROUPE_FOND}"
                cells[0] = "— " + str(cells[0]).upper()
                trs.append([(c, st) for c in cells])
            elif genre == "total":
                st = f"font-weight:bold; background-color:{C_ENTETE_FOND}"
                trs.append([(c, st) for c in cells])
            else:
                trs.append(cells)
        out.append(_table(entetes, trs, largeurs=["19%", "13%"] + [None] * 8,
                          num=tuple(range(2, len(garde)))))
        conv = getattr(ctx.nav, "convention_fsm", "max")
        out.append("<p class='d'>Sonde, volume et remplissage viennent de la table de "
                   "jaugeage du dossier ; le poids est celui que le calcul a compté, à la "
                   f"densité du point. FSM : convention « {e(conv)} » du dossier. "
                   "La densité relevée capacité par capacité et l'origine de chaque relevé "
                   "sont dans l'export « Relevé des capacités ».</p>")

    # --- cargaison, cale par cale
    out.append("<h2>3. Cargaison, cale par cale</h2>")
    cales = _cargaison_par_cale(ctx) if ctx.nav is not None else []
    if not cales:
        out.append("<p class='d'>Aucune charge posée dans les cales à ce point.</p>")
    else:
        trs = []
        t_poids = t_aire = 0.0
        for c in cales:
            t_poids += c["poids_t"]
            t_aire += c["aire_m2"]
            adm = c["admissible_t_m2"]
            moy = c["moyenne_t_m2"]
            pire = c["pire"]
            if pire is None or pire["limite"] <= 0:
                cel_pire = "—"
            else:
                trop = pire["charge"] > pire["limite"] + 1e-9
                cel_pire = (f"{pire['charge']:.2f} / {pire['limite']:.2f}",
                            f"font-weight:bold; color:{C_KO}" if trop else "")
            trs.append([
                c["pont"], c["cale"], str(c["n_poses"]), str(c["colis"]),
                f"{c['poids_t']:.2f}", f"{c['aire_m2']:.1f}",
                "—" if moy is None else f"{moy:.2f}",
                f"{adm:g}" if adm > 0 else "—",
                cel_pire,
                f"{c['lcg_m']:.2f}", f"{c['tcg_m']:+.2f}",
                ", ".join(_port(ctx, p) for p in c["ports"]) or "—",
            ])
        st = f"font-weight:bold; background-color:{C_ENTETE_FOND}"
        trs.append([("TOTAL", st), ("", st),
                    (str(sum(c["n_poses"] for c in cales)), st),
                    (str(sum(c["colis"] for c in cales)), st),
                    (f"{t_poids:.2f}", st), (f"{t_aire:.1f}", st)]
                   + [("", st)] * 6)
        out.append(_table(["Pont", "Cale", "Poses", "Colis", "Poids t", "Aire m²",
                           "Moy. t/m²", "Adm. t/m²", "Pile max / adm.", "LCG m",
                           "TCG m", "Ports de déchargement"], trs,
                          largeurs=["13%", "6%", "6%", "6%", "8%", "7%", "8%", "8%",
                                    "11%", "7%", "7%", None],
                          num=(2, 3, 4, 5, 6, 7, 8, 9, 10)))
        cond = ctx.win.condition
        # LES MARCHANDISES DANGEREUSES (D-83) : où elles sont, et si la cale les
        # admet — un tableau à part, qu'on retrouve sans lire toute la cargaison
        from .core.stowage import imdg_admis
        caps = {cap.code: cap for _d, cap in ctx.win.project.all_capacities()}
        dg = {}
        for code, lst in (cond.placements or {}).items():
            for pl in lst:
                classe = str(getattr(pl, "classe_imdg", "") or "")
                if classe:
                    cle = (code, classe)
                    dg[cle] = dg.get(cle, 0) + max(1, int(getattr(pl, "niveaux", 1) or 1))
        if dg:
            lignes_dg = []
            for (code, classe), n in sorted(dg.items()):
                admises = list(getattr(caps.get(code), "classes_imdg", []) or [])
                ok = imdg_admis(admises, classe)
                lignes_dg.append([code, classe, str(n), ", ".join(admises) or "aucune",
                                  ("admise", f"color:{C_OK}") if ok else
                                  ("NON ADMISE", f"font-weight:bold; color:{C_KO}")])
            out.append("<p class='d'><b>Marchandises dangereuses (IMDG)</b></p>")
            out.append(_table(["Cale", "Classe", "Colis", "Classes admises", "Verdict"],
                              lignes_dg, largeurs=["15%", "12%", "10%", "33%", None],
                              num=(2,)))
        inconnues = cond.cales_inconnues(ctx.win.project)
        materiel = cond.poids_materiel_bord_t() if hasattr(cond, "poids_materiel_bord_t") else 0.0
        if inconnues or materiel:
            quoi = []
            if materiel:
                quoi.append(f"le matériel du bord posé dans les cales ({materiel:.2f} t, "
                            "compté avec la cale où il est)")
            if inconnues:
                p_inc = sum(pl.poids_total_t for c in inconnues
                            for pl in cond.placements.get(c) or [])
                quoi.append(f"{p_inc:.2f} t rangées sous des cales que le plan ne "
                            f"connaît plus ({', '.join(inconnues)}), comptées au "
                            "plancher le plus haut du navire")
            out.append("<p class='d'><b>Pour recouper le bilan (section 1)</b> : ce "
                       "tableau ne montre que les cales du plan ; le bilan compte aussi "
                       + " et ".join(e(q) for q in quoi) + ".</p>")
        out.append("<p class='d'>« Moy. t/m² » rapporte le poids posé à l'aire de la "
                   "cale : c'est un ordre de grandeur, pas un contrôle. Le contrôle est "
                   "la colonne suivante — la pile la plus chargée et la charge admissible "
                   "sous SON emprise (calque des charges compris) ; elle est écrite en "
                   "rouge si elle dépasse. Rien de tout cela n'entre dans la stabilité : "
                   "le poids et ses centres sont au bilan, section 1.</p>")

    # --- flottaison
    out.append("<h2>4. Flottaison, centre de gravité et stabilité initiale</h2>")
    if not ctx.flottaison:
        out.append("<p>Aucun calcul : rien à rapporter.</p>")
    else:
        # deux colonnes de (libellé, valeur), comme le panneau — moins de pages
        flot = list(ctx.flottaison)
        moitie = (len(flot) + 1) // 2
        rows = []
        for i in range(moitie):
            a = flot[i]
            bb = flot[i + moitie] if i + moitie < len(flot) else ("", "")
            rows.append([(a[0], "color:#4E5761"), (a[1], "font-weight:bold"),
                         (bb[0], "color:#4E5761"), (bb[1], "font-weight:bold")])
        out.append(_table([], rows, largeurs=["34%", "16%", "34%", "16%"], num=(1, 3)))
        if not ctx.fiable:
            out.append(f"<p style='color:{C_KO}'><b>Valeurs hors du domaine des tables : "
                       "extrapolées, sans valeur réglementaire.</b></p>")

    # --- le relevé de tirants d'eau du bord, s'il y en a un (D-60)
    releve = _releve_du_point(ctx)
    if releve is not None:
        r, ec, corrige = releve
        rows = [
            [("Lu à la coque", "color:#4E5761"),
             r.lecture()
             + (" (déjà aux perpendiculaires)" if r.aux_perpendiculaires else " (aux repères)")
             + (f" · densité {r.densite_eau:.4f}" if r.densite_eau else "")
             + (f" · relevé du {r.date}" if r.date else "")],
            [("Ramené aux perpendiculaires", "color:#4E5761"),
             f"AR {ec.te_ar_pp_m:.3f} m · AV {ec.te_av_pp_m:.3f} m · "
             f"assiette {ec.assiette_m:+.3f} m"],
            [("Déplacement lu dans la table", "color:#4E5761"),
             f"{ec.deplacement_observe_t:,.1f} t".replace(",", " ")
             + f" · LCB {ec.lcb_observe_m:.3f} m"],
            [("Écart au chargement déclaré", "color:#4E5761"),
             (f"{ec.masse_t:+.1f} t ({ec.masse_pc:+.2f} %)"
              + (f" à x = {ec.position_m:.2f} m" if ec.position_fiable else "")
              + f" · moment {ec.moment_tm:+.0f} t·m")],
        ]
        out.append("<p></p>" + _table(["Relevé de tirants d'eau", ""], rows,
                                      largeurs=["30%", None]))
        if ec.concordent:
            out.append(f"<p class='d' style='color:{C_OK}'>Le relevé et le calcul "
                       "concordent : rien ne manque au bilan des poids.</p>")
        else:
            out.append("<p class='d'>" + (
                "Cet écart est porté au bilan des poids comme poids fictif "
                "(section 1) : le déplacement et l'assiette du calcul sont donc "
                "ceux de la coque. La hauteur de ce poids n'est pas mesurée par "
                "des tirants d'eau — il est posé au KG du point, et ne le change "
                "pas." if corrige else
                "Cet écart n'est <b>pas</b> porté au bilan des poids : le calcul "
                "de ce rapport est celui du chargement déclaré, pas celui de la "
                "coque.") + "</p>")
        for alerte in ec.alertes:
            out.append(f"<p class='d' style='color:{C_KO}'>{e(alerte)}</p>")

    # --- hydrostatiques lues à l'équilibre
    out.append("<h2>5. Hydrostatiques lues à l'équilibre</h2>")
    lignes_h = _lignes_hydro(ctx)
    if not lignes_h:
        out.append("<p class='d'>Aucun calcul : pas de ligne hydrostatique.</p>")
    else:
        moitie = (len(lignes_h) + 1) // 2
        rows = []
        for i in range(moitie):
            g = lignes_h[i]
            d = lignes_h[i + moitie] if i + moitie < len(lignes_h) else ("", "", "")
            rows.append([(g[0], "color:#4E5761"), (g[1], "font-weight:bold"),
                         (g[2], "color:#4E5761"),
                         (d[0], "color:#4E5761"), (d[1], "font-weight:bold"),
                         (d[2], "color:#4E5761")])
        out.append(_table([], rows, largeurs=["26%", "12%", "8%", "26%", "12%", "8%"],
                          num=(1, 4)))
        dom = _domaines_texte(ctx)
        out.append("<p class='d'>Valeurs interpolées dans les tables du dossier à "
                   f"l'assiette et au tirant d'eau de l'équilibre — telles que le moteur "
                   f"les a lues, sans arrondi intermédiaire."
                   + (f" Domaine des tables — {e(dom)}." if dom else "") + "</p>")

    # --- courbe GZ
    lg = int(page.largeur * 0.97)
    out.append('<table width="100%" cellpadding="0" cellspacing="0" border="0"><tr><td>'
               "<h2>6. Courbe de stabilité (GZ)</h2>"
               f'<img src="gz.png" width="{lg}" height="{lg // 2}"></td></tr></table>')
    if ctx.gz is not None and ctx.gite:
        out.append(f"<p class='d'>Courbe résiduelle : angles comptés depuis la gîte "
                   f"d'équilibre {ctx.gite:+.1f}°, du côté où le navire est couché — "
                   "c'est sur elle que les aires et le GZmax des critères sont mesurés. "
                   "L'écran trace la courbe depuis la verticale ; les chiffres sont les mêmes.</p>")

    lignes_gz = _lignes_gz(ctx)
    if lignes_gz:
        trs = []
        for l in lignes_gz:
            st = "font-weight:bold" if l["repere"] else ""
            aire = "—" if l["aire"] != l["aire"] else f"{l['aire']:.4f}"
            trs.append([(f"{l['angle']:.1f}", st), (f"{l['absolu']:+.1f}", st),
                        (f"{l['gz']:.3f}", st), (aire, st),
                        (l["repere"], f"{st}; color:{C_COURBE}" if st else "")])
        out.append(_table(["Gîte / équilibre °", "Gîte / verticale °", "GZ m",
                           "Aire cumulée m·rad", "Repère"], trs,
                          largeurs=["16%", "16%", "14%", "20%", None],
                          num=(0, 1, 2, 3)))
        out.append("<p class='d'>La même courbe, en chiffres : c'est elle que les "
                   "critères intègrent. L'aire est comptée depuis la gîte d'équilibre ; "
                   "une aire vide signifie que l'angle sort de ce que la table des "
                   "pantocarènes couvre — on ne prolonge pas une aire.</p>")

    # --- courbes limites du dossier
    out.append("<h2>7. Marge aux courbes limites du dossier (KG max / GM min)</h2>")
    lim = _courbes_limites(ctx)
    if lim is None:
        out.append("<p class='d'>Ce navire n'a pas de table de courbes limites "
                   "(« kgmax_gmmin.csv ») : rien à confronter.</p>")
    else:
        rows = []
        for lib, valeur, seuil, sens, unite in (
                ("KG effectif du point", lim["kg_effectif_m"], lim["kg_max_m"], "<=", "m"),
                ("GM corrigé du point", lim["gm_corrige_m"], lim["gm_min_m"], ">=", "m")):
            if seuil is None:
                rows.append([lib, f"{valeur:.3f}", "—", "—", unite,
                             ("NON ÉVALUABLE", f"color:{C_NA}")])
                continue
            marge = (seuil - valeur) if sens == "<=" else (valeur - seuil)
            ok = marge >= -1e-9
            st = (f"font-weight:bold; color:{C_OK if ok else C_KO}; "
                  f"background-color:{C_OK_FOND if ok else C_KO_FOND}")
            rows.append([lib, f"{valeur:.3f}",
                         {"texte": e(f"{sens} {seuil:.3f}"), "attrs": 'align="right"'},
                         f"{marge:+.3f}", unite,
                         ("DANS LA COURBE" if ok else "HORS COURBE", st)])
        out.append(_table(["Grandeur", "Valeur", "Limite du dossier", "Marge", "Unité",
                           "Situation"], rows,
                          largeurs=["34%", "12%", "16%", "12%", "8%", None],
                          num=(1, 2, 3)))
        txt = (f"Limites lues dans « kgmax_gmmin.csv » au déplacement "
               f"{lim['deplacement_t']:,.0f} t et à l'assiette {lim['assiette_m']:+.3f} m"
               .replace(",", " ") + ". ")
        if lim["critere_limitant"]:
            r = lim["ligne_citee"] or {}
            txt += ("Critère qui limite le KG max dans cette zone de la table : "
                    f"<b>{e(lim['critere_limitant'])}</b> (ligne tabulée la plus proche : "
                    f"{e(r.get('Deplacement_t', '?'))} t, assiette {e(r.get('Assiette_m', '?'))} m). ")
        txt += ("Ces courbes sont celles du dossier approuvé : elles ne remplacent pas "
                "les critères de la section suivante, elles les résument — un point dans "
                "la courbe les satisfait tous, à l'assiette où elle a été tracée.")
        if not lim["dedans"]:
            txt += (" <b>Déplacement ou assiette hors de la table des courbes limites : "
                    "la valeur ci-dessus est extrapolée, elle n'a aucune valeur "
                    "réglementaire.</b>")
        out.append(f"<p class='d'>{txt}</p>")

    # --- critères
    out.append("<h2>8. Critères réglementaires (voilure portée au point)</h2>")
    # LES RÉGLEMENTATIONS APPLIQUÉES (D-79) : ce que le navire a retenu dans la
    # bibliothèque, avec le texte, la version et le statut de chacune — un
    # rapport qui ne dit pas CONTRE QUOI il juge ne se relit pas
    retenues = getattr(ctx.win, "_retenues", None)
    if callable(retenues) and ctx.nav is not None:
        from .core.reglements import STATUTS
        lignes = []
        for x in retenues():
            r = x.reglement
            statut = STATUTS.get(r.statut, r.statut)
            st = f"color:{C_KO}; font-weight:bold" if r.a_relire else ""
            surch = (", ".join(f"{k} = {v:g}" for k, v in x.seuils.items())
                     if x.seuils else "")
            lignes.append([r.titre, r.texte, r.version, (statut, st),
                           surch or "—"])
        if lignes:
            out.append(_table(["Réglementation", "Texte", "Version", "Statut",
                               "Seuils propres au dossier"], lignes,
                              largeurs=["26%", "40%", "10%", "10%", None]))
    if ctx.voilure:
        # le point final de la description du dossier ne doit pas en faire deux
        detail = (ctx.voilure_detail or "").rstrip(" .")
        out.append(f"<p class='d'>Voilure portée à ce point : <b>{e(ctx.voilure)}</b>"
                   + (f" — {e(detail)}" if detail else "")
                   + ". C'est elle qui décide du critère de vent appliqué et de "
                     "la surface exposée, lue au tirant d'eau d'équilibre.</p>")
    rep = ctx.rep
    if rep is None or not rep.checks:
        msg = ("Aucun critère évaluable pour cet état." if rep is not None
               else "Aucun calcul : critères non évalués.")
        out.append(_cadre(e(msg), C_NA_FOND, C_NA, "NON ÉVALUABLE"))
    else:
        rows = []
        groupe_courant = ""
        for chk in rep.checks:
            # les critères de vent dépendent de la voilure portée : ils sont
            # imprimés sous leur propre titre, comme les groupes du bilan
            groupe = getattr(chk, "groupe", "") or ""
            if groupe != groupe_courant:
                groupe_courant = groupe
                if groupe:
                    rows.append(_ligne_groupe(groupe, 6))
            evaluable = getattr(chk, "evaluable", True)
            information = getattr(chk, "information", False)
            if information:
                # une information n'a pas de seuil, donc pas de marge ni de
                # verdict : le dossier l'imprime comme un résultat
                v = "non calculable" if not evaluable else format_nombre(chk.valeur, chk.unite)
                txt = "NON ÉVALUABLE" if not evaluable else "information"
                st = f"color:{C_NA}" + ("" if evaluable else f"; background-color:{C_NA_FOND}")
                rows.append([(chk.libelle, f"color:{C_NA}"), v, "—", "—",
                             chk.unite, (txt, st)])
                continue
            if evaluable:
                marge = chk.valeur - chk.seuil
                if chk.comparaison != ">=":
                    marge = -marge
                v = format_nombre(chk.valeur, chk.unite)
                m = ("+" if marge >= 0 else "") + format_nombre(marge, chk.unite)
                txt, coul, fond = (("CONFORME", C_OK, C_OK_FOND) if chk.ok
                                   else ("NON CONFORME", C_KO, C_KO_FOND))
            else:
                v, m = "non calculable", "—"
                txt, coul, fond = "NON ÉVALUABLE", C_NA, C_NA_FOND
            st = f"font-weight:bold; color:{coul}; background-color:{fond}"
            # « <= 27.73 » commence par un chevron : `_table` y verrait du HTML
            # déjà formé et la cellule disparaîtrait à l'impression. On la
            # passe donc en cellule toute faite, échappée ici.
            seuil = {"texte": e(f"{chk.comparaison} {format_nombre(chk.seuil, chk.unite)}"
                                if chk.seuil == chk.seuil else "—"),
                     "attrs": 'align="right"'}
            rows.append([chk.libelle, v, seuil, m, chk.unite, (txt, st)])
        out.append(_table(["Critère", "Valeur", "Seuil", "Marge", "Unité", "Verdict"], rows,
                          largeurs=["40%", "12%", "12%", "12%", "9%", "15%"], num=(1, 2, 3)))
        ok = rep.ok
        verdict = ctx.verdict
        coul, fond = ((C_OK, C_OK_FOND) if (ok and ctx.fiable) else (C_KO, C_KO_FOND))
        if verdict in ("HORS DOMAINE", "NON ÉVALUABLE"):
            coul, fond = C_NA, C_NA_FOND
        out.append("<p></p>" + _cadre(
            f"<span style='font-size:12pt; color:{coul}'><b>Verdict : {e(verdict)}</b></span>"
            + ("" if ctx.fiable else " — calcul hors du domaine des tables, verdict sans "
               "valeur réglementaire"), fond, coul))

    # --- toutes les voilures
    voil = _voilures_comparees(ctx)
    if voil:
        out.append("<h2>9. Le même chargement sous chaque voilure</h2>")
        trs = []
        for v in voil:
            lignes = v["lignes"]
            nom = v["nom"] + (" — portée au point" if v["porte"] else "")
            if v["erreur"]:
                trs.append([(nom, "font-weight:bold"), "—", "—", "—", "—", "—",
                            (f"non évaluable : {v['erreur']}", f"color:{C_NA}")])
                continue
            meteo = "Critère météo" in (v["titre"] or "")
            surface = v.get("surface_m2")
            if meteo:
                # sous le critère météo, le vent n'est pas un résultat : il est
                # IMPOSÉ (504 Pa, IS2008 §2.3). On écrit donc la pression du
                # critère, pas une force admissible — et on ne convertit pas
                # ces 504 Pa en nœuds : la correspondance du recueil n'est pas
                # celle de la formule NR500, et inventer l'écart serait mentir.
                pression = (ctx.nav.criteres.get("critere_meteo", {}) or {}).get(
                    "pression_vent_pa", 504.0) if ctx.nav is not None else 504.0
                vent = f"{float(pression):g} Pa imposés"
                if surface:
                    vent += f" · {float(pression) * float(surface):,.0f} N".replace(",", " ")
                angle = _valeur_code(lignes, "METEO_THETA0", 2)
                lib_angle = "θ0 sous vent établi"
                aire = _valeur_code(lignes, "METEO_AIRE", 4)
            else:
                f = _valeur_code(lignes, "NR500_VOILE_F", 0)
                v_nd = _valeur_code(lignes, "NR500_VOILE_V", 1)
                vent = (f"{f} N" if f != "—" else "—")
                if v_nd != "—":
                    vent += f" · {v_nd} nd"
                angle = _valeur_code(lignes, "NR500_VOILE_ANG", 2)
                lib_angle = "angle statique"
                aire = _valeur_code(lignes, "NR500_VOILE_AIRE", 4)
            verdict = v["verdict"]
            if verdict == "INCOMPLET":
                manquants = [c.libelle for c in lignes
                             if not c.information and not c.evaluable]
                verdict = f"INCOMPLET ({len(manquants)} critère(s) non évaluable(s))"
                v["manquants"] = manquants
            coul, fond = {"CONFORME": (C_OK, C_OK_FOND),
                          "NON CONFORME": (C_KO, C_KO_FOND)}.get(v["verdict"], (C_NA, C_NA_FOND))
            st = f"font-weight:bold; color:{coul}; background-color:{fond}"
            trs.append([(nom, "font-weight:bold" if v["porte"] else ""),
                        "météo IS2008" if meteo else "NR500 voilier",
                        "—" if surface is None else f"{float(surface):,.0f}".replace(",", " "),
                        vent,
                        {"texte": f"{e(angle)}<br><span style='color:{C_NA}'>{e(lib_angle)}</span>",
                         "attrs": 'align="right"'},
                        aire, (verdict, st)])
        out.append(_table(["Configuration", "Critère", "Surface m²",
                           "Vent", "Angle °", "Aire m·rad", "Verdict du critère de vent"], trs,
                          largeurs=["20%", "11%", "8%", "17%", "12%", "9%", None],
                          num=(2, 5)))
        out.append("<p class='d'>Le <b>même chargement</b>, le même équilibre et la même "
                   "courbe GZ, sous chacune des configurations que le dossier décrit : "
                   "seule change la surface exposée au vent, donc le critère appliqué et "
                   "la force que le navire encaisse avant son angle statique limite. "
                   "C'est ce que l'écran afficherait en déroulant le sélecteur de voilure. "
                   "Sous le critère météo (voiles enroulées) le vent n'est pas un résultat "
                   "mais une donnée du critère — les 504 Pa d'IS2008 §2.3 —, là où sous "
                   "voile la force et la vitesse sont ce que le navire encaisse avant son "
                   "angle statique limite : les deux colonnes ne se comparent pas. "
                   
                   "<b>Seule la ligne de la voilure portée fait le verdict du point</b> "
                   "(section 8) ; les autres disent ce qu'il en serait si l'on changeait "
                   "la toile, sans rien toucher au chargement.</p>")
        for v in voil:
            for lib in v.get("manquants") or []:
                out.append(f"<p class='d'>Voilure « {e(v['nom'])} » : critère non "
                           f"évaluable sur ce point — {e(lib)}. Un critère non évaluable "
                           "n'est pas un critère satisfait : le verdict de cette ligne "
                           "reste incomplet.</p>")
        vues = set()
        for v in voil:
            for m in v["messages"]:
                if m not in vues and ("Plan de réduction" in m or "hors des cas" in m):
                    vues.add(m)
                    out.append(f"<p class='d'>{e(m)}</p>")

    # --- ouvertures d'envahissement
    ouvertures = []
    if ctx.nav is not None and ctx.eq is not None:
        try:
            from .core import stability as _stab
            from .mainwindow import _te_val
            ouvertures = _stab.classement_envahissement(
                ctx.nav, _te_val(ctx.eq, "TE_AR_m", ctx.eq.draft_m),
                _te_val(ctx.eq, "TE_AV_m", ctx.eq.draft_m))
        except Exception:                  # pas de table, ou dossier sans repères
            ouvertures = []
    if ouvertures:
        out.append("<h2>10. Ouvertures et angle d'envahissement</h2>")
        trs = []
        for i, o in enumerate(ouvertures[:12]):
            st = f"font-weight:bold; color:{C_KO}" if i == 0 else ""
            trs.append([(o["repere"] or "—", st), o["fonction"] or "—",
                        (f"{o['x_m']:.2f}", st), (f"{o['y_m']:+.2f}", st),
                        (f"{o['z_m']:.2f}", st), (f"{o['tirant_local_m']:.2f}", st),
                        (f"{o['franc_bord_m']:.2f}", st),
                        ("—" if o["angle_deg"] is None else f"{o['angle_deg']:.1f}", st)])
        out.append(_table(["Repère", "Fonction", "X m", "Y m", "Z m",
                           "Tirant d'eau local m", "Franc-bord local m",
                           "Gîte d'immersion °"], trs,
                          largeurs=["13%", None, "7%", "7%", "7%", "10%", "10%", "13%"],
                          num=(2, 3, 4, 5, 6, 7)))
        reste = len(ouvertures) - len(trs)
        out.append("<p class='d'>Les ouvertures du dossier, de la première immergée à la "
                   "dernière" + (f" ({reste} autre(s) non imprimée(s))" if reste > 0 else "")
                   + " : la première, en rouge, est celle qui donne l'angle "
                   "d'envahissement θf du calcul. Angles approchés — muraille verticale au "
                   "droit du point, franc-bord local pris sur la pente de flottaison ; "
                   "comptés depuis la verticale, donc réduits d'autant par une gîte "
                   "permanente. Ce tableau ne sert pas au verdict : il dit dans quel ordre "
                   "le pont entre dans l'eau, et de combien on est loin de la suivante.</p>")

    # --- réserves
    out.append("<h2>11. Réserves et messages du moteur</h2>")
    if ctx.reserves:
        out.append("<ul>" + "".join(f"<li>{e(r)}</li>" for r in ctx.reserves) + "</ul>")
    else:
        out.append("<p class='d'>Aucune réserve émise par le moteur pour ce calcul.</p>")
    if ctx.theta_f is not None:
        out.append("<p class='d'>Angle d'envahissement θf approché : muraille verticale, "
                   "≈ 3° sous le calcul sur coque.</p>")
    out.append(f"<p class='d'>{e(AVERTISSEMENT)}</p>")

    # --- profil et coupe
    if "profil.png" in ressources:
        img = ressources["profil.png"]
        lg = int(page.largeur * 0.97)
        # la figure d'abord, son titre en légende dessous : une image ne se
        # coupe pas, elle passe entière à la page suivante et le titre la suit
        # — un titre placé au-dessus restait orphelin en bas de page. Elle est
        # posée dans un tableau d'une cellule, comme la courbe GZ : la
        # figure et tableau se paginent de la même façon, et la courbe GZ
        # est déjà posée ainsi : deux figures, un seul idiome.
        out.append('<table width="100%" cellpadding="0" cellspacing="0" border="0">'
                   f'<tr><td><img src="profil.png" width="{lg}" '
                   f'height="{int(lg * img.height() / max(1, img.width()))}"></td></tr>'
                   "</table>")
        # D-10 : on nomme ce qu'on montre. Tant que la forme est reconstituée
        # depuis les tables, elle est « schématique » ; dès qu'un plan des
        # formes est décalqué, c'est ce plan qu'on nomme — dans les deux cas
        # la figure situe et ne mesure rien, et les chiffres viennent du calcul.
        try:
            from .profil_view import formes_du_bord, nom_du_trace
            formes = formes_du_bord(getattr(ctx.nav, "path", None))
        except Exception:                      # pragma: no cover
            formes = None
        if formes is None:
            trace = ("silhouette schématique reconstituée depuis les tables "
                     "(ce n'est pas le plan des formes, D-10)")
        else:
            trace = (f"{nom_du_trace(formes).lower()} — un tracé, qui sert à "
                     "situer et jamais au calcul (D-10)")
        out.append("<h2>12. Profil et coupe au maître</h2>"
                   f"<p class='d'>Figure ci-dessus : {trace} ; les chiffres sont "
                   "ceux du calcul.</p>")
    # Les sections 9, 10 et 12 n'existent pas toujours (pas de voilure, pas de
    # points d'envahissement, pas de profil) : on renumérote dans l'ordre, pour
    # qu'un rapport ne passe pas de 9 à 11 comme s'il manquait une page (RS-7)
    import re as _re
    compteur = iter(range(1, 100))
    return _re.sub(r"<h2>\d+\. ", lambda _m: f"<h2>{next(compteur)}. ",
                   "\n".join(out))


def ressources_rapport(ctx):
    res = {"gz.png": image_gz(ctx)}
    if ctx.eq is not None:
        img = image_profil(ctx.win)
        if img is not None and not img.isNull():
            res["profil.png"] = img
    return res


# ================================================= l'aperçu de CE document
# Le bord (22/09/2026) : « dans les exports, l'aperçu ne montre que l'aperçu
# de la stab, pas l'aperçu de ce que l'on a sélectionné dans la liste. » (D-62)
#
# Chaque document se décrit maintenant à part de son écriture : un `_doc_*`
# rend (titre, construire_html, ressources, paysage), et l'écriture n'est plus
# qu'un `ecrire_pdf` de ce quadruplet. L'aperçu avant impression peint donc
# EXACTEMENT le document coché, avec la même mise en page — et non un second
# rendu qui finirait par diverger. Les deux planches A3 peintes à la main
# (plans cotés, plan des dockers) exposent le même service sous la forme
# `_preparer` + `peindre_sur`.

def document(win, cle, ctx=None, port=None):
    """(titre, html, ressources, paysage) du document `cle`, ou None si ce
    document ne se peint pas (un CSV seul) ou n'existe pas."""
    ctx = ctx or Contexte(win)
    if cle == "rapport":
        res = ressources_rapport(ctx)
        return ("Rapport de stabilité", lambda page: html_rapport(ctx, page, res),
                res, False)
    if cle == "capacites":
        return _doc_capacites(ctx)
    if cle == "chargement":
        manif = _lignes_manifeste(ctx)
        lignes = []
        for i, (pl, cap, deck, lot) in enumerate(_lignes_posees(ctx), 1):
            origine = ("charge du bord" if lot is not None and lot.hors_manifeste
                       else (lot.nom if lot is not None
                             else ("matériel du bord" if pl.est_materiel_bord
                                   else "hors manifeste")))
            lignes.append([i, deck.name if deck else "?",
                           cap.code if cap else "cale inconnue",
                           lot.nom if lot else "", pl.nom, pl.type_code or "—",
                           pl.x, pl.y, f"{pl.rot}°", pl.niveaux, pl.poids_t,
                           pl.poids_total_t, ctx.escales.nom_de(pl.port_dechargement),
                           _code(ctx, pl.port_dechargement), "", origine])
        return _doc_chargement(ctx, manif, lignes)
    if cle == "plan":
        return _doc_plan(win, ctx)
    if cle == "pointage":
        return _doc_pointage(win, ctx, "chargement", port)
    return None


# Les documents peints à la main : (module, sous-titre pour l'aperçu)
PEINTS = {"plans_cotes": "plans_cotes", "plan_dockers": "plan_dockers"}


def peindre_document(win, cle, device, ctx=None, port=None):
    """Peint le document `cle` sur un périphérique (aperçu, imprimante).

    Rend le titre peint, ou None si ce document ne se peint pas — un CSV seul
    (le journal) n'a pas d'aperçu, et la fenêtre d'export le dit plutôt que
    de montrer le rapport à sa place."""
    ctx = ctx or Contexte(win)
    if cle in PEINTS:
        if cle == "plans_cotes":
            from . import plans_cotes as module
            titre = "Plans cotés des cales"
        else:
            from . import plan_dockers as module
            titre = "Plan de chargement pour les dockers"
        module._preparer(device, ctx, win)
        module.peindre_sur(device, win, ctx)
        return titre
    doc = document(win, cle, ctx, port)
    if doc is None:
        return None
    titre, html, res, paysage = doc
    _preparer(device, paysage, f"{titre} — {ctx.navire}")
    peindre(device, ctx, titre, html, res)
    return titre


def exporter_rapport(win, chemin, ctx=None):
    ctx = ctx or Contexte(win)
    res = ressources_rapport(ctx)
    return ecrire_pdf(chemin, ctx, "Rapport de stabilité",
                      lambda page: html_rapport(ctx, page, res), res)


def imprimer_rapport(win, printer, ctx=None, ressources=None):
    """Sur une QPrinter (aperçu ou impression) : même mise en page que le PDF.

    `ressources` : les images déjà fabriquées. L'aperçu avant impression
    redemande le dessin à chaque changement de page ou de zoom ; refaire la
    courbe GZ et la vue de profil à chaque fois n'apporte rien — le contexte
    est figé au moment où l'aperçu s'ouvre, les images le sont donc aussi."""
    ctx = ctx or Contexte(win)
    _preparer(printer, False)
    res = ressources if ressources is not None else ressources_rapport(ctx)
    return peindre(printer, ctx, "Rapport de stabilité",
                   lambda page: html_rapport(ctx, page, res), res)


def html_rapport_seul(win):
    """Le HTML du rapport sans périphérique (tests, débogage) — largeur écran."""
    ctx = Contexte(win)
    res = ressources_rapport(ctx)

    class _P:
        largeur, k = 700, 1.0
    return html_rapport(ctx, _P, res)


# ================================================================ 2. capacités
def _lignes_capacites(ctx):
    """Le tableau des capacités, ligne à ligne, avec les mêmes agrégats que la
    vue Capacités (`tanks_table._Agregat`, `fsm_compte`)."""
    from .core.groupes import grouper
    from .tanks_table import _Agregat, _contenu, fsm_compte
    nav = ctx.nav
    caps = getattr(nav, "capacities", {}) or {}
    cond = ctx.win.condition
    tanks = {t.capacite: t for t in cond.tanks}
    groupes = grouper([t.capacite for t in cond.tanks], caps)
    total = _Agregat()
    out = []                  # (genre, valeurs)
    for nom_g, noms in groupes:
        a = _Agregat()
        for nom in noms:
            a.ajouter(tanks[nom], nav)
        total.fusionner(a)
        out.append(("groupe", [nom_g, "", "", "", a.volume if a.volume else None,
                               a.pc_moyen if a.poids else None, a.poids if a.poids else None,
                               a.vcg if a.poids else None, a.lcg if a.poids else None,
                               a.tcg if a.poids else None, a.fsm if a.fsm else None,
                               f"{a.n} capacité(s), {a.n_slack} en carène liquide"]))
        for nom in noms:
            t = tanks[nom]
            # la capacité TELLE QUE CHARGÉE : le rapport imprime le poids que
            # le calcul a compté, donc à la densité du point
            cap = t.capacite_chargee(nav)
            ligne = t.ligne(nav)
            contenu = _contenu(cap) if cap is not None else "capacité inconnue du navire"
            # On n'imprime JAMAIS un poids sans dire quelle densité l'a
            # produit : la colonne porte la densité employée et, si elle
            # s'écarte du dossier, celle du dossier entre parenthèses.
            dens = _densite_cellule(t, cap, nav)
            if ligne is None:
                vals = [nom, contenu, dens,
                        t.valeur if t.mesure == "sonde" else None,
                        t.valeur if t.mesure == "volume" else None,
                        t.valeur if t.mesure == "pourcent" else None,
                        None, None, None, None, None,
                        t.probleme or ("relevé " + t.mesure)]
            else:
                vals = [nom, contenu, dens,
                        float(ligne["Sondage_m"]) if "Sondage_m" in ligne else None,
                        float(ligne["Volume_m3"]), float(ligne["Remplissage_pc"]),
                        float(ligne["Poids_t"]), float(ligne["VCG_m"]), float(ligne["LCG_m"]),
                        float(ligne.get("TCG_m", 0.0)), fsm_compte(ligne, cap, nav),
                        (f"relevé : {t.mesure}"
                         + (" · densité relevée à ce point, hors dossier"
                            if t.densite_modifiee(nav) else ""))]
            out.append(("tank", vals))
    out.append(("total", ["TOTAL CAPACITÉS", "", "", "", total.volume,
                          total.pc_moyen if total.poids else None, total.poids,
                          total.vcg if total.poids else None, total.lcg if total.poids else None,
                          total.tcg if total.poids else None, total.fsm,
                          f"{total.n} capacité(s), {total.n_slack} en carène liquide"]))
    return out


def _densite_cellule(t, cap, nav):
    """La densité de la colonne « d » du rapport : celle qui a fait le poids.

    Texte et non nombre, parce qu'une densité relevée au point doit être lue
    À CÔTÉ de celle du dossier : « 0,840 (dossier : 0,870) ». Un poids imprimé
    sans sa densité ne se vérifie pas, et une densité imprimée sans dire d'où
    elle vient se prend pour celle du dossier."""
    if cap is None:
        return ""
    txt = _bilan.densite_texte(cap.density)
    if t.densite_modifiee(nav):
        txt += f" (dossier : {_bilan.densite_texte(cap.densite_dossier)})"
    return txt


COLS_CAPACITES = ["Capacité", "Contenu", "d", "Sonde m", "Volume m³", "%",
                  "Poids t", "VCG m", "LCG m", "TCG m", "FSM t·m", "Note"]
# la densité est déjà écrite en français par `_densite_cellule` (et porte sa
# mention « dossier : … ») : `None` laisse la cellule telle quelle
_ND_CAP = [None, None, None, 3, 2, 1, 2, 2, 2, 2, 2, None]


def _doc_capacites(ctx):
    """(titre, html, ressources, paysage) du relevé des capacités.

    Le document est décrit à part de son écriture (D-62) : l'aperçu avant
    impression peint LE MÊME document que le PDF, sans le réécrire — le bord
    ne veut pas un aperçu du rapport quand il a coché « capacités »."""
    lignes = _lignes_capacites(ctx)

    def html(page):
        out = [_STYLE, _identification_html(ctx, "Relevé des capacités", complet=False), "<p></p>"]
        trs = []
        for genre, vals in lignes:
            cells = [vals[0], vals[1]] + [
                _nb(v, nd, signe=(i + 2 == 9)).replace(",", ".") if nd else (v or "")
                for i, (v, nd) in enumerate(zip(vals[2:], _ND_CAP[2:]))]
            if genre == "groupe":
                st = f"font-weight:bold; background-color:{C_GROUPE_FOND}"
                cells[0] = "— " + str(cells[0]).upper()
                trs.append([(c, st) for c in cells])
            elif genre == "total":
                st = f"font-weight:bold; background-color:{C_ENTETE_FOND}"
                trs.append([(c, st) for c in cells])
            else:
                trs.append(cells)
        out.append(_table(COLS_CAPACITES, trs, num=(2, 3, 4, 5, 6, 7, 8, 9, 10)))
        conv = getattr(ctx.nav, "convention_fsm", "max")
        out.append(f"<p class='d'>Sonde, volume et pourcentage viennent de la table de jaugeage "
                   f"du dossier ; la colonne « Note » dit laquelle a été relevée à bord. "
                   f"FSM compté comme le moteur : nul hors carène liquide, convention « {e(conv)} » sinon.</p>")
        return "\n".join(out)

    return "Relevé des capacités", html, None, True


def exporter_capacites(win, dossier, ctx=None):
    ctx = ctx or Contexte(win)
    if ctx.nav is None:
        return []
    lignes = _lignes_capacites(ctx)
    csv_path = os.path.join(dossier, ctx.nom_fichier("capacites", "csv"))
    rows = _entete_csv(ctx, "Relevé des capacités") + [["Genre"] + COLS_CAPACITES]
    for genre, vals in lignes:
        rows.append([genre] + [_nb(v, nd, signe=(i == 9)) if nd else (v or "")
                               for i, (v, nd) in enumerate(zip(vals, _ND_CAP))])
    ecrire_csv(csv_path, rows)

    pdf_path = os.path.join(dossier, ctx.nom_fichier("capacites", "pdf"))
    titre, html, res, paysage = _doc_capacites(ctx)
    ecrire_pdf(pdf_path, ctx, titre, html, res, paysage=paysage)
    return [csv_path, pdf_path]


# ================================================================ 3. chargement
def _lignes_manifeste(ctx):
    from .core.cargo_model import couleur_hex
    cond = ctx.win.condition
    attribue = cond.places_par_ligne()
    out = []
    for r, m in enumerate(cond.manifeste):
        place = attribue[r]
        reste = m.quantite - place
        out.append({
            "lot": m.nom, "type": "BORD" if m.hors_manifeste else (m.type_code or "—"),
            "quantite": m.quantite, "pose": place, "reste": reste,
            "poids_unit": m.poids_t, "poids_total": m.poids_total_t,
            # le débord se lit à côté des cotes : la palette mesure ceci, le
            # lot occupe cela — c'est ce que le bord doit retrouver sur le
            # quai comme sur le plan (D-39)
            "dims": (f"{m.longueur_m:g} × {m.largeur_m:g} × {m.hauteur_m:g}"
                     + (f" (+{m.debord_m:g} débord)" if m.debord_m > 0 else "")),
            "gerbable": m.gerbable_max,
            "port_ch": _port(ctx, m.port_chargement),
            "port_dech": _port(ctx, m.port_dechargement),
            "code_ch": _code(ctx, m.port_chargement),
            "code_dech": _code(ctx, m.port_dechargement),
            # le nom normalisé par la liste des escales : deux orthographes
            # d'un même quai ne font qu'une ligne dans un tableur
            "nom_ch": ctx.escales.nom_de(m.port_chargement),
            "nom_dech": ctx.escales.nom_de(m.port_dechargement),
            "cale": m.cale_imposee, "couleur": couleur_hex(m), "note": getattr(m, "note", ""),
            "bord": m.hors_manifeste, "lot_id": m.lot_id,
        })
    return out


def _code(ctx, nom):
    """Le code UN/LOCODE de l'escale, vide s'il n'est pas connu du navire. Une
    colonne à part dans les CSV : un tableur trie et rapproche sur le code."""
    liste = getattr(ctx, "escales", None)
    p = liste.trouver(nom) if (liste is not None and (nom or "").strip()) else None
    return p.code if p is not None else ""


def _lignes_posees(ctx):
    """(placement, cale, pont, lot) pour tout le navire, dans l'ordre des
    ponts puis des cales — celui de la fenêtre « Charges posées »."""
    cond = ctx.win.condition
    lots = {m.lot_id: m for m in cond.manifeste}
    out = []
    for deck in ctx.win.project.sorted_decks():
        for cap in deck.capacities:
            for pl in cond.placements.get(cap.code) or []:
                out.append((pl, cap, deck, lots.get(pl.lot_id)))
    # cales que le projet ne connaît plus : le poids ne disparaît pas
    codes = {cap.code for _, cap in ctx.win.project.all_capacities()}
    for code, lst in cond.placements.items():
        if code not in codes:
            for pl in lst:
                out.append((pl, None, None, lots.get(pl.lot_id)))
    return out


COLS_MANIFESTE = ["Lot", "Type", "Quantité", "Posé", "Reste", "Poids unitaire t",
                  "Poids total t", "L × l × h m", "Stack", "Port de chargement",
                  "Code chargement", "Port de déchargement", "Code déchargement",
                  "Cale imposée", "Couleur", "Note"]
COLS_POSEES = ["N°", "Pont", "Cale", "Lot", "Charge", "Type", "X m", "Y m", "Rotation",
               "Niveaux", "Poids unitaire t", "Poids total t", "Port de déchargement",
               "Code déchargement", "Couleur", "Origine"]


def _doc_chargement(ctx, manif, lignes_posees):
    """(titre, html, ressources, paysage) du manifeste et des charges posées."""
    from .core.cargo_model import couleur_hex
    def html(page):
        out = [_STYLE, _identification_html(ctx, "Chargement : manifeste et charges posées", complet=False),
               "<h2>1. Manifeste</h2>"]
        if not manif:
            out.append("<p>Rien au manifeste.</p>")
        else:
            trs = []
            tq = tp = tr = tw = 0.0
            for m in manif:
                pastille = {"texte": "&nbsp;", "attrs": f'bgcolor="{m["couleur"]}"'}
                if m["bord"]:
                    pose, reste = "—", "—"
                else:
                    tq += m["quantite"]; tp += m["pose"]; tr += max(0, m["reste"]); tw += m["poids_total"]
                    pose = str(m["pose"])
                    reste = (str(m["reste"]) if m["reste"] > 0
                             else ("✓ complet" if m["reste"] == 0 else f"+{-m['reste']} en trop"))
                    reste = (reste, f"color:{C_OK if m['reste'] == 0 else C_KO}")
                trs.append([pastille, m["lot"], m["type"], str(m["quantite"]), pose, reste,
                            f"{m['poids_unit']:g}", f"{m['poids_total']:.2f}", m["dims"],
                            str(m["gerbable"]), m["port_ch"] or "—", m["port_dech"] or "—",
                            m["cale"] or "—"])
            st = f"font-weight:bold; background-color:{C_ENTETE_FOND}"
            trs.append([("", st), ("Total manifeste", st), ("", st), (f"{tq:g}", st),
                        (f"{tp:g}", st), (f"{tr:g}", st), ("", st), (f"{tw:.2f}", st),
                        ("", st), ("", st), ("", st), ("", st), ("", st)])
            out.append(_table(["", "Lot", "Type", "Qté", "Posé", "Reste", "Unit. t", "Total t",
                               "L × l × h", "Stack", "Port ch.", "Port déch.", "Cale"], trs,
                              largeurs=["3%"] + [None] * 12, num=(3, 4, 5, 6, 7)))
        out.append("<h2>2. Charges posées</h2>")
        if not lignes_posees:
            out.append("<p>Aucune charge posée.</p>")
        else:
            trs = []
            poids = 0.0
            for l in lignes_posees:
                trs.append([str(l[0]), l[1], l[2], l[3] or l[15], l[4], f"{l[6]:.2f}", f"{l[7]:.2f}",
                            l[8], str(l[9]), f"{l[10]:g}", f"{l[11]:.2f}",
                            _port(ctx, l[12]) or "—"])
                poids += l[11]
            st = f"font-weight:bold; background-color:{C_ENTETE_FOND}"
            trs.append([("", st), (f"{len(lignes_posees)} charge(s)", st)] + [("", st)] * 8
                       + [(f"{poids:.2f}", st), ("", st)])
            out.append(_table(["N°", "Pont", "Cale", "Lot", "Charge", "X m", "Y m", "Rot.",
                               "Niv.", "Unit. t", "Total t", "Port déch."], trs,
                              num=(0, 5, 6, 8, 9, 10)))
        return "\n".join(out)


    return "Chargement", html, None, True


def exporter_chargement(win, dossier, ctx=None):
    from .core.cargo_model import couleur_hex
    ctx = ctx or Contexte(win)
    manif = _lignes_manifeste(ctx)
    posees = _lignes_posees(ctx)

    rows = _entete_csv(ctx, "Manifeste") + [COLS_MANIFESTE]
    for m in manif:
        rows.append([m["lot"], m["type"], m["quantite"],
                     "" if m["bord"] else m["pose"], "" if m["bord"] else m["reste"],
                     _nb(m["poids_unit"], 3), _nb(m["poids_total"], 2), m["dims"],
                     m["gerbable"], m["nom_ch"], m["code_ch"], m["nom_dech"],
                     m["code_dech"], m["cale"], m["couleur"], m["note"]])
    csv_manif = os.path.join(dossier, ctx.nom_fichier("manifeste", "csv"))
    ecrire_csv(csv_manif, rows)

    rows = _entete_csv(ctx, "Charges posées") + [COLS_POSEES]
    lignes_posees = []
    for i, (pl, cap, deck, lot) in enumerate(posees, 1):
        origine = ("charge du bord" if lot is not None and lot.hors_manifeste
                   else (lot.nom if lot is not None else ("matériel du bord" if pl.est_materiel_bord else "hors manifeste")))
        l = [i, deck.name if deck else "?", cap.code if cap else "cale inconnue",
             lot.nom if lot else "", pl.nom, pl.type_code or "—",
             pl.x, pl.y, f"{pl.rot}°", pl.niveaux, pl.poids_t, pl.poids_total_t,
             ctx.escales.nom_de(pl.port_dechargement),
             _code(ctx, pl.port_dechargement),
             couleur_hex(pl), origine]
        lignes_posees.append(l)
        rows.append([l[0], l[1], l[2], l[3], l[4], l[5], _nb(l[6], 2), _nb(l[7], 2), l[8],
                     l[9], _nb(l[10], 3), _nb(l[11], 2), l[12], l[13], l[14], l[15]])
    csv_posees = os.path.join(dossier, ctx.nom_fichier("charges_posees", "csv"))
    ecrire_csv(csv_posees, rows)

    titre, html, res, paysage = _doc_chargement(ctx, manif, lignes_posees)
    pdf = os.path.join(dossier, ctx.nom_fichier("chargement", "pdf"))
    ecrire_pdf(pdf, ctx, titre, html, res, paysage=paysage)
    return [csv_manif, csv_posees, pdf]


# ================================================================ 4. plan
def _doc_plan(win, ctx):
    """(titre, html, ressources, paysage) du plan de chargement, un pont
    par page."""
    from .core.cargo_model import couleur_hex
    from .project import KIND_CONTOUR
    decks = [d for d in win.project.sorted_decks()
             if any(c.kind != KIND_CONTOUR and len(c.points) >= 3 for c in d.capacities)]
    cond = win.condition
    lots = {m.lot_id: m for m in cond.manifeste}
    res = {}
    for i, d in enumerate(decks):
        res[f"pont{i}.png"] = image_plan(win, d)

    def html(page):
        out = [_STYLE]
        if not decks:
            out.append(_identification_html(ctx, "Plan de chargement", complet=False))
            out.append("<p>Aucune cale tracée : pas de plan.</p>")
        for i, d in enumerate(decks):
            if i > 0:
                out.append("<p style='page-break-before:always'></p>")
            out.append(f"<h1>Plan de chargement — {e(d.name)} (z = {d.z:g} m)</h1>"
                       f"<p class='d'>{e(ctx.navire)} — {e(ctx.point_texte)}</p>")
            img = res[f"pont{i}.png"]
            # l'image tient dans la page avec la légende dessous : hauteur bornée
            h_max = int(getattr(page, "hauteur_corps", page.largeur * 0.6) * 0.62)
            w = int(page.largeur)
            h = int(w * img.height() / max(1, img.width()))
            if h > h_max:
                h = h_max
                w = int(h * img.width() / max(1, img.height()))
            out.append(f'<p><img src="pont{i}.png" width="{w}" height="{h}"></p>')
            # légende : les lots présents sur ce pont, avec compte et poids
            compte = {}
            for cap in d.capacities:
                for pl in cond.placements.get(cap.code) or []:
                    cle = pl.lot_id or (pl.type_code or pl.nom)
                    c = compte.setdefault(cle, [pl, 0, 0.0, set()])
                    c[1] += max(1, pl.niveaux)
                    c[2] += pl.poids_total_t
                    c[3].add(cap.code)
            trs = []
            for cle, (pl, n, w_t, cales) in compte.items():
                lot = lots.get(cle)
                nom = lot.nom if lot else pl.nom
                port = _port(ctx, (lot.port_dechargement if lot
                                   else pl.port_dechargement)) or "—"
                trs.append([{"texte": "&nbsp;", "attrs": f'bgcolor="{couleur_hex(lot or pl)}"'},
                            nom, pl.type_code or "—", str(n), f"{w_t:.2f}", port,
                            ", ".join(sorted(cales))])
            if trs:
                out.append(_table(["", "Lot", "Type", "Colis", "Poids t", "Port de déchargement",
                                   "Cales"], trs, largeurs=["3%", None, "10%", "8%", "10%", "22%", "22%"],
                                  num=(3, 4)))
            else:
                out.append("<p class='d'>Aucune charge posée sur ce pont.</p>")
        return "\n".join(out)


    return "Plan de chargement", html, res, True


def exporter_plan(win, chemin, ctx=None):
    """Un pont par page, paysage : le plan tel que la vue Chargement le peint,
    la légende des lots et le compte par cale."""
    ctx = ctx or Contexte(win)
    titre, html, res, paysage = _doc_plan(win, ctx)
    return ecrire_pdf(chemin, ctx, titre, html, res, paysage=paysage)


# ================================================================ 5. pointage
def ports_de_dechargement(win):
    """Les ports de déchargement des charges posées et du manifeste.

    Les **noms**, une seule fois chacun : c'est ce qui sert à filtrer les
    colis (`exporter_pointage`) et à remplir le choix de la fenêtre d'export.
    Deux écritures d'une même escale — « Pointe à Pitre » et
    « Pointe-à-Pitre » — n'en font qu'une : sans cela le bord recevrait deux
    feuilles de pointage pour un seul quai, chacune avec la moitié des colis.
    L'orthographe retenue est celle de la liste des escales du navire quand
    elle connaît le port ; la première rencontrée sinon."""
    escales = _ports.liste_du_bord(win)
    ports, vus = [], set()
    cond = win.condition
    lus = [pl.port_dechargement for lst in cond.placements.values() for pl in lst]
    lus += [m.port_dechargement for m in cond.manifeste]
    for nom in lus:
        nom = escales.nom_de(nom)
        cle = _ports._cle_nom(nom)
        if not cle or cle in vus:
            continue
        vus.add(cle)
        ports.append(nom)
    return ports


def _doc_pointage(win, ctx, mode="chargement", port=None):
    """(titre, html, ressources, paysage) d'une feuille de pointage."""
    from .core.cargo_model import couleur_hex
    posees = _lignes_posees(ctx)
    if port:
        # on compare des ESCALES, pas des chaînes : un colis marqué
        # « Pointe à Pitre » part bien à Pointe-à-Pitre
        posees = [t for t in posees
                  if _ports.meme_port(ctx.escales.nom_de(t[0].port_dechargement), port)]
    cond = win.condition
    ordre_lots = {m.lot_id: i for i, m in enumerate(cond.manifeste)}
    posees.sort(key=lambda t: (ordre_lots.get(t[0].lot_id, len(ordre_lots)),
                               t[0].lot_id or t[0].type_code or t[0].nom,
                               t[2].z if t[2] else 1e9, t[1].code if t[1] else "",
                               t[0].x, t[0].y))
    titre = ("Feuille de pointage — déchargement" if mode == "dechargement"
             else "Feuille de pointage — chargement") \
        + (f" — {_port(ctx, port)}" if port else "")
    res = {"case.png": image_case()}

    def html(page):
        out = [_STYLE, _identification_html(ctx, titre, complet=False), "<p></p>"]
        if not posees:
            out.append("<p>Aucun colis"
                       + (f" à décharger à {e(_port(ctx, port))}" if port else " posé")
                       + ".</p>")
            return "\n".join(out)
        k = page.px(12)
        case = f'<img src="case.png" width="{k}" height="{k}">'
        trs = []
        lot_courant = object()
        n = 0
        for pl, cap, deck, lot in posees:
            cle = pl.lot_id or (pl.type_code or pl.nom)
            if cle != lot_courant:
                lot_courant = cle
                nom_lot = lot.nom if lot else pl.nom
                nb = sum(max(1, q.niveaux) for q, _c, _d, _l in posees
                         if (q.lot_id or (q.type_code or q.nom)) == cle)
                trs.append([{"texte": "&nbsp;", "attrs": f'bgcolor="{couleur_hex(lot or pl)}"'},
                            {"texte": f"<b>{e(nom_lot)}</b> — {nb} colis"
                                      + (f" — port de déchargement : "
                                         f"{e(_port(ctx, lot.port_dechargement))}"
                                         if lot and lot.port_dechargement else ""),
                             "attrs": f'colspan="10" bgcolor="{C_GROUPE_FOND}"'}])
            n += 1
            cx, cy = pl.centre
            trs.append(["", str(n), lot.nom if lot else "—", pl.type_code or pl.nom,
                        f"{deck.name if deck else '?'} · {cap.code if cap else '?'}",
                        f"{cx:.2f} / {cy:.2f}", str(pl.niveaux), f"{pl.poids_total_t:.2f}",
                        _port(ctx, pl.port_dechargement) or "—", case, ""])
        out.append(_table(["", "N°", "Lot", "Type", "Cale", "Position X / Y m", "Niveaux",
                           "Poids t", "Port de déchargement", "Pointé", "Observations"], trs,
                          largeurs=["2%", "4%", "16%", "9%", "14%", "12%", "6%", "7%", "12%", "5%", None],
                          num=(1, 6, 7)))
        out.append(f"<p class='d'>{n} ligne(s) — une ligne par colis ou par pile (colonne "
                   "Niveaux). Position : centre de l'emprise, repère navire.</p>")
        return "\n".join(out)


    return titre, html, res, True


def exporter_pointage(win, chemin, mode="chargement", port=None, ctx=None):
    """Une ligne par colis posé (une pile = une ligne, avec ses niveaux), par
    lot puis par cale, avec une case à cocher. `mode` : « chargement » (tout
    ce qui est à bord, ou le port choisi) ou « dechargement » (le port choisi
    seulement)."""
    ctx = ctx or Contexte(win)
    titre, html, res, paysage = _doc_pointage(win, ctx, mode, port)
    return ecrire_pdf(chemin, ctx, titre, html, res, paysage=paysage)


def exporter_pointages(win, dossier, port=None, ctx=None):
    """La feuille de chargement (tout, ou le port choisi), puis une feuille de
    déchargement par port — ou pour le seul port demandé."""
    ctx = ctx or Contexte(win)
    out = [exporter_pointage(win, os.path.join(dossier, ctx.nom_fichier(
        "pointage_chargement" + (f"_{_sur(port)}" if port else ""), "pdf")),
        "chargement", port, ctx)]
    ports = [port] if port else ports_de_dechargement(win)
    for p in ports:
        out.append(exporter_pointage(win, os.path.join(dossier, ctx.nom_fichier(
            f"pointage_dechargement_{_sur(p)}", "pdf")), "dechargement", p, ctx))
    return out


# ================================================================ 6. journal
COLS_JOURNAL = ["N°", "Date", "Lieu", "Libellé", "État", "Déplacement", "TE AR", "TE AV",
                "Assiette", "Gîte", "GM corrigé", "Verdict", "Version du calcul", "Note"]


def lignes_journal(win):
    """Un point par ligne ; les résultats d'un point figé sont son instantané
    (`point.resultats`), ceux du point courant ce que le bandeau affiche."""
    journal = win.journal
    points = list(journal.points()) if journal is not None else []
    courant = win.point
    if courant is not None and not any(p.numero == courant.numero for p in points):
        points.append(courant)
        points.sort(key=lambda p: (p.numero, p.horodatage))
    out = []
    for p in points:
        res = None
        if p.fige and p.resultats:
            res = p.resultats
        elif courant is not None and p.numero == courant.numero and not p.fige:
            res = win.resultats_courants()
        res = res or {}
        out.append([p.numero, p.date_lisible, p.lieu, p.libelle,
                    "figé" if p.fige else "en cours",
                    res.get("deplacement", ""), res.get("te_ar", ""), res.get("te_av", ""),
                    res.get("assiette", ""), res.get("gite", ""), res.get("gm", ""),
                    res.get("verdict", ""), res.get("version", ""), p.note])
    return out


def exporter_journal(win, chemin, ctx=None):
    ctx = ctx or Contexte(win)
    rows = _entete_csv(ctx, "Journal des points") + [COLS_JOURNAL] + lignes_journal(win)
    return ecrire_csv(chemin, rows)


# ================================================================ tout
def tout_exporter(win, dossier, choix=None, port=None):
    """Écrit les exports demandés (`choix` : clés de EXPORTS, tous par défaut)
    et renvoie les chemins écrits, dans l'ordre."""
    ctx = Contexte(win)
    choix = set(choix) if choix is not None else {c for c, _ in EXPORTS}
    os.makedirs(dossier, exist_ok=True)
    ecrits = []
    if "rapport" in choix:
        ecrits.append(exporter_rapport(win, os.path.join(dossier, ctx.nom_fichier("rapport", "pdf")), ctx))
    if "capacites" in choix:
        ecrits.extend(exporter_capacites(win, dossier, ctx))
    if "chargement" in choix:
        ecrits.extend(exporter_chargement(win, dossier, ctx))
    if "plan" in choix:
        ecrits.append(exporter_plan(win, os.path.join(dossier, ctx.nom_fichier("plan", "pdf")), ctx))
    if "plans_cotes" in choix:
        from . import plans_cotes
        ecrits.append(plans_cotes.exporter(
            win, os.path.join(dossier, ctx.nom_fichier("plans_cotes", "pdf")), ctx))
    if EXPORT_DOCKERS[0] in choix:
        from . import plan_dockers
        ecrits.append(plan_dockers.exporter(
            win, os.path.join(dossier, plan_dockers.nom_fichier(ctx)), ctx))
    if "pointage" in choix:
        ecrits.extend(exporter_pointages(win, dossier, port, ctx))
    if "journal" in choix:
        ecrits.append(exporter_journal(win, os.path.join(dossier, ctx.nom_fichier("journal", "csv")), ctx))
    return ecrits
