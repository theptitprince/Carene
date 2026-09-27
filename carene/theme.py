# -*- coding: utf-8 -*-
"""Thème de Carène : la palette, la feuille de style et les icônes.

Aucune ressource externe : les icônes sont dessinées au QPainter, donc
l'exécutable reste autonome et net à toutes les résolutions.

Les couleurs sont des variables de module mises à jour par `set_mode()` :
les vues graphiques les lisent au moment du dessin, si bien qu'un changement
de thème se répercute immédiatement.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)

# ---------------------------------------------------------------- palettes
LIGHT = dict(
    BG_DEEP="#E8EDF3",     # fond des vues graphiques (les plans blancs s'y détachent)
    BG_APP="#F3F6FA",
    SURFACE="#FFFFFF",
    SURFACE_2="#EDF1F7",
    BORDER="#C7D2DF",
    BORDER_SOFT="#DDE4ED",
    TEXT="#1D2733",
    TEXT_DIM="#46546A",
    TEXT_FAINT="#5B6B7F",    # ≥ 4,5:1 sur toutes les surfaces claires (notes, aides)
    ACCENT="#0B7A73",
    ACCENT_DARK="#095F5A",
    ACCENT_SOFT="#D6EFEC",
    ACCENT_TEXT="#FFFFFF",
    WARN="#8F4C0A",
    WARN_SOFT="#FBEEDC",
    DANGER="#C0392B",
    OK="#1F6E44",
    HOVER="#E3EAF3",
    PRESSED="#D6DFEA",
    SCROLL="#BAC6D4",
    SCROLL_HOVER="#9FAEC0",
    TOOLTIP_BG="#243244",
    TOOLTIP_TEXT="#F2F6FB",
    # vues graphiques
    GRID_X=(20, 110, 155, 120),
    GRID_Y=(25, 130, 85, 105),
    TRAIT_CONSTRUCTION=(176, 48, 48, 190),
    CAP_EDGE=(10, 110, 160),
    CAP_BASE=(30, 125, 200, 30),
    CAP_FILL=(60, 150, 215, 115),
    CAP_SEL=(224, 123, 21),
    DECK_LINE=(138, 75, 196),
    CONTOUR=(107, 122, 141),
    MARKER_BG=(255, 255, 255, 232),
    ISO_PLATE=(90, 115, 150, 34),
    ISO_PLATE_EDGE=(95, 118, 148, 150),
    ISO_SIDE=(45, 135, 205, 42),
    ISO_TOP=(45, 135, 205, 72),
    ISO_LIQ=(40, 130, 200, 132),
    ISO_EDGE=(20, 105, 155, 175),
)

# PLUS DE THÈME SOMBRE (D-72). Le bord : « pas de thème sombre, on a dit ».
# Une seule palette, la claire : un poste de passerelle se lit de jour, et
# deux palettes à tenir d'accord — icônes, vues, aide, exports — c'était
# deux fois plus d'occasions d'un texte illisible que personne ne demandait.
MODE = "light"          # gardé pour ce qui le lisait : il ne change plus

# noms exportés (remplis par set_mode)
BG_DEEP = BG_APP = SURFACE = SURFACE_2 = BORDER = BORDER_SOFT = ""
TEXT = TEXT_DIM = TEXT_FAINT = ""
ACCENT = ACCENT_DARK = ACCENT_SOFT = ACCENT_TEXT = ""
WARN = WARN_SOFT = DANGER = OK = HOVER = PRESSED = SCROLL = SCROLL_HOVER = ""
TOOLTIP_BG = TOOLTIP_TEXT = ""
GRID_X = GRID_Y = CAP_EDGE = CAP_BASE = CAP_FILL = CAP_SEL = None
TRAIT_CONSTRUCTION = None
DECK_LINE = CONTOUR = MARKER_BG = None
ISO_PLATE = ISO_PLATE_EDGE = ISO_SIDE = ISO_TOP = ISO_LIQ = ISO_EDGE = None


def set_mode(mode: str = "light"):
    """Charge la palette (la seule, la claire — D-72). `mode` est ignoré :
    l'argument reste pour ce qui l'appelait encore avec « light »."""
    g = globals()
    for key, val in LIGHT.items():
        g[key] = QColor(*val) if isinstance(val, tuple) else val


set_mode("light")


def font_family() -> str:
    return "Segoe UI, Inter, DejaVu Sans, Helvetica, Arial"


def stylesheet() -> str:
    return f"""
* {{ font-family: {font_family()}; }}

QWidget {{ background: {BG_APP}; color: {TEXT}; font-size: 11px; }}

QMainWindow::separator {{ background: {BORDER_SOFT}; width: 4px; height: 4px; }}
QMainWindow::separator:hover {{ background: {ACCENT_SOFT}; }}

/* ---------------------------------------------------------- menus */
QMenuBar {{
    background: {SURFACE};
    border-bottom: 1px solid {BORDER_SOFT};
    padding: 2px 4px;
}}
QMenuBar::item {{ padding: 3px 9px; border-radius: 5px; background: transparent; }}
QMenuBar::item:selected {{ background: {SURFACE_2}; }}
QMenu {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 5px;
}}
QMenu::item {{ padding: 4px 20px 4px 10px; border-radius: 5px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; }}
QMenu::separator {{ height: 1px; background: {BORDER_SOFT}; margin: 5px 8px; }}

/* ---------------------------------------------------------- barre d'outils */
QToolBar {{
    background: {SURFACE};
    border: none;
    border-bottom: 1px solid {BORDER_SOFT};
    padding: 5px 7px;
    spacing: 3px;
}}
QToolBar::separator {{ background: {BORDER}; width: 1px; margin: 5px 7px; }}
/* l'en-tête de la fenêtre principale : l'ancienne barre d'outils, devenue
   un bloc qui passe à la ligne (D-67) */
QFrame#entete {{
    background: {SURFACE};
    border: none;
    border-bottom: 1px solid {BORDER_SOFT};
}}
QToolButton {{
    background: transparent;
    color: {TEXT_DIM};
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 5px 10px;
    font-weight: 500;
}}
QToolButton:hover {{ background: {HOVER}; color: {TEXT}; }}
QToolButton:checked {{
    background: {ACCENT_SOFT};
    color: {ACCENT_DARK};
    border: 1px solid {ACCENT};
    font-weight: bold;
}}
QToolButton:disabled {{ color: {TEXT_FAINT}; }}

/* ---------------------------------------------------------- docks */
QDockWidget {{ color: {TEXT_DIM}; }}
QDockWidget::title {{
    background: {SURFACE};
    border-bottom: 1px solid {BORDER_SOFT};
    padding: 7px 10px;
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 1px;
}}
QDockWidget > QWidget {{ background: {SURFACE}; }}

/* ---------------------------------------------------------- arbre */
QTreeWidget {{ background: {SURFACE}; border: none; outline: 0; padding: 4px; }}
QTreeWidget::item {{ padding: 3px 4px; border-radius: 5px; color: {TEXT_DIM}; }}
QTreeWidget::item:hover {{ background: {HOVER}; color: {TEXT}; }}
QTreeWidget::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT_DARK}; }}

/* ---------------------------------------------------------- champs */
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 3px 6px;
    color: {TEXT};
    selection-background-color: {ACCENT};
    selection-color: {ACCENT_TEXT};
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid {ACCENT};
}}
QDoubleSpinBox::up-button, QSpinBox::up-button,
QDoubleSpinBox::down-button, QSpinBox::down-button {{
    background: transparent; border: none; width: 14px;
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
}}

/* ---------------------------------------------------------- boutons */
QPushButton {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 4px 10px;
    font-weight: 500;
}}
QPushButton:hover {{ background: {HOVER}; border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {PRESSED}; }}
QPushButton:disabled {{
    color: {TEXT_FAINT}; background: {SURFACE_2}; border-color: {BORDER_SOFT};
}}
QPushButton[accent="1"] {{
    background: {ACCENT};
    color: {ACCENT_TEXT};
    border: 1px solid {ACCENT};
    font-weight: bold;
}}
QPushButton[accent="1"]:hover {{ background: {ACCENT_DARK}; border-color: {ACCENT_DARK}; }}
QPushButton[accent="1"]:disabled {{
    background: {ACCENT_SOFT}; color: {TEXT_FAINT}; border-color: {ACCENT_SOFT};
}}
QPushButton[ghost="1"] {{
    background: transparent; border: 1px solid {BORDER}; color: {TEXT_DIM};
}}
QPushButton[ghost="1"]:hover {{ color: {TEXT}; border-color: {ACCENT}; background: {HOVER}; }}
/* un bouton « ghost » cochable sert d'onglet : ponts, vues, outils. Coché, il
   doit se voir sans ambiguïté — sinon on ne sait plus sur quel pont on pose. */
QPushButton[ghost="1"]:checked {{
    background: {ACCENT_SOFT}; color: {ACCENT_DARK}; border-color: {ACCENT};
}}
QPushButton[ghost="1"]:checked:hover {{ background: {ACCENT_SOFT}; color: {ACCENT_DARK}; }}

/* ---------------------------------------------------------- divers */
QSlider::groove:horizontal {{ height: 5px; background: {SURFACE_2}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    width: 15px; margin: -6px 0; border-radius: 8px;
    background: {ACCENT}; border: 2px solid {SURFACE};
}}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {SCROLL}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {SCROLL_HOVER}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {SCROLL}; border-radius: 5px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {SCROLL_HOVER}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QStatusBar {{
    background: {SURFACE};
    border-top: 1px solid {BORDER_SOFT};
    color: {TEXT_DIM};
    padding: 3px 8px;
}}
QStatusBar::item {{ border: none; }}

QToolTip {{
    background: {TOOLTIP_BG};
    color: {TOOLTIP_TEXT};
    border: 1px solid {ACCENT_DARK};
    border-radius: 5px;
    padding: 5px 8px;
}}

QGraphicsView {{ border: none; background: {BG_DEEP}; }}

QLabel#viewHeader {{
    background: {SURFACE};
    color: {TEXT_DIM};
    border-bottom: 1px solid {BORDER_SOFT};
    border-left: 3px solid {ACCENT};
    padding: 3px 10px;
    font-size: 10px;
    font-weight: bold;
    letter-spacing: 1px;
}}
QLabel#hint {{ color: {TEXT_DIM}; font-size: 10px; }}
QLabel#pill {{
    border-radius: 8px; padding: 2px 9px; font-size: 10px; font-weight: bold;
    background: {SURFACE_2}; color: {TEXT_DIM};
}}
QLabel#pill[tone="ok"]   {{ background: {ACCENT_SOFT}; color: {OK}; }}
QLabel#pill[tone="warn"] {{ background: {WARN_SOFT}; color: {WARN}; }}
QLabel#pill[tone="todo"] {{ background: {SURFACE_2}; color: {TEXT_FAINT}; }}

/* ---------------------------------------------------------- panneau stabilité */
QFrame#card {{
    background: {SURFACE}; border: 1px solid {BORDER_SOFT}; border-radius: 6px;
}}
QLabel#cardTitle {{
    color: {TEXT}; font-size: 11px; font-weight: bold;
    text-transform: uppercase; letter-spacing: 1px;
}}
/* sans ceci, chaque QLabel peint son propre fond BG_APP par-dessus la carte
   et laisse une bande grise visible autour du texte */
QFrame#card > QLabel, QFrame#card QCheckBox {{ background: transparent; }}
QTableWidget {{
    background: {SURFACE}; border: 1px solid {BORDER_SOFT}; border-radius: 6px;
    gridline-color: {BORDER_SOFT}; outline: 0; color: {TEXT};
    selection-background-color: {ACCENT_SOFT}; selection-color: {ACCENT_DARK};
}}
QTableWidget::item {{ padding: 1px 4px; color: {TEXT}; }}
QLabel#avertissement {{ background: {WARN_SOFT}; color: {TEXT}; border-bottom: 1px solid {WARN}; font-size: 11px; }}
QTableWidget::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT_DARK}; }}
QTableWidget::item:disabled {{ color: {TEXT_FAINT}; }}
/* une boîte de dialogue est une fenêtre à part : sans règle explicite, elle
   peut retomber sur les couleurs du style natif de la plate-forme */
QDialog {{ background: {BG_APP}; color: {TEXT}; }}
QHeaderView::section {{
    background: {SURFACE_2}; color: {TEXT_DIM}; border: none;
    border-bottom: 1px solid {BORDER_SOFT}; padding: 3px 5px; font-weight: bold;
    font-size: 10px;
}}
QTableWidget QLineEdit {{ border-radius: 0px; }}
"""


def apply_theme(app, mode: str = "light"):
    """Applique palette + feuille de style. `mode` est ignoré (D-72)."""
    set_mode(mode)
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(BG_APP))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Base, QColor(SURFACE))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(SURFACE_2))
    pal.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Button, QColor(SURFACE))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(ACCENT_TEXT))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(TOOLTIP_BG))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(TOOLTIP_TEXT))
    app.setPalette(pal)
    f = QFont()
    f.setPointSize(9)
    app.setFont(f)
    app.setStyleSheet(stylesheet())


# ---------------------------------------------------------------- icônes
def _pen(painter, color, width=1.7):
    p = QPen(QColor(color), width)
    p.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(p)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _d_ship(p, c):
    _pen(p, c)
    path = QPainterPath(QPointF(3, 13))
    path.lineTo(17, 13)
    path.lineTo(14.5, 17)
    path.lineTo(5.5, 17)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(10, 3), QPointF(10, 13))
    p.drawLine(QPointF(10, 5), QPointF(15, 10))
    p.drawLine(QPointF(10, 5), QPointF(5, 10))


def _d_folder(p, c):
    _pen(p, c)
    p.drawRoundedRect(QRectF(3, 6, 14, 11), 2, 2)
    p.drawLine(QPointF(3, 6), QPointF(8, 6))
    p.drawLine(QPointF(8, 6), QPointF(9.5, 3.5))
    p.drawLine(QPointF(9.5, 3.5), QPointF(3, 3.5))


def _d_save(p, c):
    _pen(p, c)
    p.drawRoundedRect(QRectF(3.5, 3.5, 13, 13), 2, 2)
    p.drawRect(QRectF(6.5, 3.5, 7, 5))
    p.drawRect(QRectF(6, 11, 8, 5.5))


def _d_image(p, c):
    _pen(p, c)
    p.drawRoundedRect(QRectF(3, 4.5, 14, 11), 2, 2)
    p.drawEllipse(QPointF(7.5, 8.5), 1.4, 1.4)
    path = QPainterPath(QPointF(4, 14))
    path.lineTo(8.5, 10)
    path.lineTo(11.5, 12.5)
    path.lineTo(13.5, 10.5)
    path.lineTo(16, 13.5)
    p.drawPath(path)


def _d_target(p, c):
    _pen(p, c)
    p.drawEllipse(QPointF(10, 10), 6, 6)
    p.drawEllipse(QPointF(10, 10), 2.2, 2.2)
    p.drawLine(QPointF(10, 1.5), QPointF(10, 4.5))
    p.drawLine(QPointF(10, 15.5), QPointF(10, 18.5))
    p.drawLine(QPointF(1.5, 10), QPointF(4.5, 10))
    p.drawLine(QPointF(15.5, 10), QPointF(18.5, 10))


def _d_decks(p, c):
    _pen(p, c)
    for y in (5, 10, 15):
        path = QPainterPath(QPointF(3, y))
        path.lineTo(10, y - 2.6)
        path.lineTo(17, y)
        path.lineTo(10, y + 2.6)
        path.closeSubpath()
        p.drawPath(path)


def _d_polygon(p, c):
    _pen(p, c)
    path = QPainterPath(QPointF(4, 8))
    path.lineTo(10, 3.5)
    path.lineTo(16.5, 7)
    path.lineTo(15, 15)
    path.lineTo(6, 16)
    path.closeSubpath()
    p.drawPath(path)
    p.setBrush(QColor(c))
    for pt in ((4, 8), (10, 3.5), (16.5, 7), (15, 15), (6, 16)):
        p.drawEllipse(QPointF(*pt), 1.3, 1.3)


def _d_contour(p, c):
    pen = QPen(QColor(c), 1.7)
    pen.setStyle(Qt.PenStyle.DashLine)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath(QPointF(3, 10))
    path.cubicTo(QPointF(6, 4), QPointF(14, 4), QPointF(17, 10))
    path.cubicTo(QPointF(14, 16), QPointF(6, 16), QPointF(3, 10))
    p.drawPath(path)


def _d_grid(p, c):
    _pen(p, c, 1.4)
    for i in (3, 8.7, 14.3):
        p.drawLine(QPointF(i, 3), QPointF(i, 17))
        p.drawLine(QPointF(3, i), QPointF(17, i))
    p.drawLine(QPointF(17, 3), QPointF(17, 17))
    p.drawLine(QPointF(3, 17), QPointF(17, 17))


def _d_fit(p, c):
    _pen(p, c)
    for dx, dy, sx, sy in ((3, 3, 1, 1), (17, 3, -1, 1),
                           (3, 17, 1, -1), (17, 17, -1, -1)):
        p.drawLine(QPointF(dx, dy), QPointF(dx + 4.5 * sx, dy))
        p.drawLine(QPointF(dx, dy), QPointF(dx, dy + 4.5 * sy))


def _d_wand(p, c):
    _pen(p, c)
    p.drawLine(QPointF(3.5, 16.5), QPointF(12.5, 7.5))
    p.drawLine(QPointF(11, 6), QPointF(14, 9))
    for cx, cy, r in ((15.5, 4.5, 2.2), (17, 11, 1.5), (9, 3, 1.5)):
        p.drawLine(QPointF(cx - r, cy), QPointF(cx + r, cy))
        p.drawLine(QPointF(cx, cy - r), QPointF(cx, cy + r))


def _d_trash(p, c):
    _pen(p, c)
    p.drawLine(QPointF(3.5, 5.5), QPointF(16.5, 5.5))
    p.drawRoundedRect(QRectF(5.5, 5.5, 9, 11.5), 1.5, 1.5)
    p.drawLine(QPointF(8, 3), QPointF(12, 3))
    p.drawLine(QPointF(8, 3), QPointF(8, 5.5))
    p.drawLine(QPointF(12, 3), QPointF(12, 5.5))


def _d_theme(p, c):
    _pen(p, c)
    p.drawEllipse(QPointF(10, 10), 6, 6)
    path = QPainterPath(QPointF(10, 4))
    path.arcTo(QRectF(4, 4, 12, 12), 90, -180)
    path.closeSubpath()
    p.setBrush(QColor(c))
    p.drawPath(path)


def _d_help(p, c):
    """Le « ? » de l'aide : un point d'interrogation dans son cercle.

    Le crochet est tracé d'un seul chemin (`arcMoveTo` pose le crayon sur le
    début de l'arc, sinon Qt relie la position courante à l'arc par un trait
    parasite), puis redescend sur une hampe verticale."""
    _pen(p, c)
    p.drawEllipse(QPointF(10, 10), 7.2, 7.2)
    cadre = QRectF(7.6, 4.4, 4.8, 4.8)
    path = QPainterPath()
    path.arcMoveTo(cadre, 200)
    path.arcTo(cadre, 200, -230)
    path.lineTo(QPointF(10, 10.6))
    path.lineTo(QPointF(10, 12.4))
    p.drawPath(path)
    p.setBrush(QColor(c))
    p.drawEllipse(QPointF(10, 14.8), 0.95, 0.95)


def _d_undo(p, c):
    """Une flèche qui revient sur ses pas : Ctrl+Z (D-61)."""
    _pen(p, c)
    chemin = QPainterPath()
    # l'arc du retour, puis la pointe de la flèche à son départ
    chemin.moveTo(4.5, 11.0)
    chemin.arcTo(QRectF(4.5, 4.5, 11.0, 11.0), 180, -230)
    p.drawPath(chemin)
    p.drawLine(QPointF(4.5, 11.0), QPointF(1.8, 7.6))
    p.drawLine(QPointF(4.5, 11.0), QPointF(8.6, 9.6))


_DRAW = {
    "undo": _d_undo,
    "ship": _d_ship, "folder": _d_folder, "save": _d_save, "image": _d_image,
    "target": _d_target, "decks": _d_decks, "polygon": _d_polygon,
    "contour": _d_contour, "grid": _d_grid, "fit": _d_fit, "wand": _d_wand,
    "trash": _d_trash, "theme": _d_theme, "help": _d_help,
}


def icon(name: str, color: str | None = None, size: int = 20) -> QIcon:
    """Icône vectorielle dessinée à la volée (états normal / actif / choisi)."""
    draw = _DRAW.get(name)
    base = color or TEXT_DIM
    ic = QIcon()
    for state_color, mode in ((base, QIcon.Mode.Normal),
                              (TEXT, QIcon.Mode.Active),
                              (ACCENT_DARK, QIcon.Mode.Selected)):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        if draw is not None:
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.scale(size / 20.0, size / 20.0)
            draw(p, state_color)
            p.end()
        ic.addPixmap(pm, mode)
    return ic
