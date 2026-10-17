"""Rounded dark/light theme + procedurally drawn icons (no binary assets)."""
import math

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (QBrush, QColor, QFont, QGuiApplication, QIcon, QLinearGradient, QPainter, QPainterPath,
                         QPalette, QPen, QPixmap, QPolygonF)

DARK = dict(mode="dark", bg="#1c1c22", panel="#2a2a32", panel2="#34343d", border="#4a4a55", text="#f5f5f7",
            muted="#a0a0aa", accent="#0a84ff", canvas="#101014", hover="#3c3c46", field="#2f2f38",
            # glass (QSS rgba strings)
            g_win="rgba(26,26,34,150)", g_panel="rgba(255,255,255,26)", g_panel2="rgba(255,255,255,36)",
            g_hover="rgba(255,255,255,52)", g_border="rgba(255,255,255,52)", g_field="rgba(0,0,0,70)",
            g_menu="rgba(30,30,38,232)", g_canvas="rgba(8,8,14,80)")
LIGHT = dict(mode="light", bg="#f0f0f6", panel="#ffffff", panel2="#ebebf2", border="#d4d4de", text="#1c1c1e",
             muted="#6a6a74", accent="#0a84ff", canvas="#dcdce6", hover="#e2e2ea", field="#ffffff",
             g_win="rgba(244,244,252,165)", g_panel="rgba(255,255,255,120)", g_panel2="rgba(255,255,255,170)",
             g_hover="rgba(255,255,255,210)", g_border="rgba(255,255,255,190)", g_field="rgba(255,255,255,170)",
             g_menu="rgba(250,250,254,238)", g_canvas="rgba(255,255,255,70)")
C = dict(DARK)

# legacy names used by older modules
BG, PANEL, BORDER, TEXT, MUTED, ACCENT = DARK["bg"], DARK["panel"], DARK["border"], DARK["text"], DARK["muted"], DARK["accent"]


def px(n):
    s = QGuiApplication.primaryScreen()
    return int(round(n * s.logicalDotsPerInch() / 96.0)) if s else int(n)


def build_style(c):
    from . import fonts
    r = px(14)
    acc = "qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #4aa3ff,stop:1 #0a84ff)"
    return f"""
* {{ font-family: "{fonts.family()}", "Segoe UI", "Malgun Gothic"; font-size: 9pt; }}
QWidget {{ color: {c['text']}; }}
QMainWindow, QDialog {{ background: {c['bg']}; }}
QMainWindow[glass="true"], QDialog[glass="true"], QWidget[glass="true"] {{ background: {c['g_win']}; }}
QToolTip {{ background: {c['g_menu']}; color: {c['text']}; border: 1px solid {c['g_border']}; border-radius: {px(10)}px; padding: {px(5)}px {px(9)}px; }}
QFrame#pill, QFrame#panel {{ background: {c['g_panel']}; border: 1px solid {c['g_border']}; border-radius: {px(22)}px; }}
QToolButton {{ background: transparent; border: none; border-radius: {px(16)}px; padding: {px(6)}px; color: {c['text']}; }}
QToolButton:hover {{ background: {c['g_hover']}; }}
QToolButton:pressed {{ background: {c['g_panel2']}; }}
QToolButton:checked {{ background: {acc}; }}
QToolButton:disabled {{ color: {c['muted']}; }}
QPushButton {{ background: {c['g_panel2']}; border: 1px solid {c['g_border']}; border-radius: {r}px; padding: {px(6)}px {px(16)}px; }}
QPushButton:hover {{ background: {c['g_hover']}; }}
QPushButton:pressed {{ background: {c['g_panel']}; }}
QPushButton:checked {{ background: {acc}; color: white; border: none; }}
QPushButton#primary {{ background: {acc}; color: white; font-weight: 600; border: none; }}
QPushButton#primary:hover {{ background: #4aa3ff; }}
QPushButton#flat {{ background: transparent; border: none; }}
QPushButton#flat:hover {{ background: {c['g_hover']}; }}
QMenu {{ background: {c['g_menu']}; border: 1px solid {c['g_border']}; border-radius: {px(18)}px; padding: {px(8)}px; }}
QMenu::item {{ padding: {px(8)}px {px(26)}px {px(8)}px {px(12)}px; border-radius: {px(11)}px; margin: 1px 0; }}
QMenu::item:selected {{ background: {acc}; color: white; }}
QMenu::item:disabled {{ color: {c['muted']}; }}
QMenu::separator {{ height: 1px; background: {c['g_border']}; margin: {px(5)}px {px(8)}px; }}
QMenu::indicator {{ width: {px(14)}px; height: {px(14)}px; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QKeySequenceEdit {{ background: {c['g_field']}; border: 1px solid {c['g_border']}; border-radius: {r}px; padding: {px(5)}px {px(10)}px; }}
QComboBox::drop-down {{ border: none; width: {px(22)}px; }}
QComboBox QAbstractItemView {{ background: {c['g_menu']}; border: 1px solid {c['g_border']}; border-radius: {px(12)}px; selection-background-color: {c['accent']}; outline: none; padding: {px(4)}px; }}
QTabWidget::pane {{ border: none; background: transparent; }}
QTabBar::tab {{ background: transparent; padding: {px(8)}px {px(18)}px; color: {c['muted']}; border-radius: {px(16)}px; margin: 2px; }}
QTabBar::tab:selected {{ color: {c['text']}; background: {c['g_panel2']}; border: 1px solid {c['g_border']}; }}
QCheckBox {{ spacing: {px(8)}px; }}
QCheckBox::indicator {{ width: {px(36)}px; height: {px(20)}px; border-radius: {px(10)}px; border: 1px solid {c['g_border']}; background: {c['g_panel2']}; image: url({_switch('off')}); }}
QCheckBox::indicator:checked {{ background: #30d158; border-color: #30d158; image: url({_switch('on')}); }}
QSlider:horizontal {{ min-height: {px(28)}px; }}
QSlider::groove:horizontal {{ height: {px(4)}px; background: {c['g_panel2']}; border-radius: {px(2)}px; }}
QSlider::handle:horizontal {{ background: white; border: 1px solid rgba(0,0,0,40); width: {px(14)}px; height: {px(14)}px; margin: {-px(6)}px 0; border-radius: {px(8)}px; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: {px(2)}px; }}
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ border-radius: {px(16)}px; padding: {px(6)}px; color: {c['muted']}; }}
QListWidget::item:selected {{ background: {c['g_panel2']}; color: {c['text']}; border: 2px solid {c['accent']}; }}
QListWidget::item:hover {{ background: {c['g_hover']}; }}
QScrollBar:vertical {{ background: transparent; width: {px(10)}px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['g_hover']}; border-radius: {px(4)}px; min-height: {px(30)}px; }}
QScrollBar:horizontal {{ background: transparent; height: {px(10)}px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['g_hover']}; border-radius: {px(4)}px; min-width: {px(30)}px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QGraphicsView {{ border: none; border-radius: {px(22)}px; background: {c['g_canvas']}; }}
QStatusBar {{ background: transparent; color: {c['muted']}; }}
QLabel#muted {{ color: {c['muted']}; }}
"""


_sw_cache = {}


def _switch(state):
    """iOS-style switch graphic for QCheckBox::indicator (written once to the data dir)."""
    if state in _sw_cache:
        return _sw_cache[state]
    from .settings import data_dir
    path = data_dir() / f"switch_{state}.png"
    w, h = 72, 40
    pm = QPixmap(w, h)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    k = 32
    x = w - k - 4 if state == "on" else 4
    p.setBrush(QColor(0, 0, 0, 55))
    p.drawEllipse(QRectF(x, 5, k, k))
    p.setBrush(QColor("white"))
    p.drawEllipse(QRectF(x, 4, k, k))
    p.end()
    pm.save(str(path), "PNG")
    _sw_cache[state] = str(path).replace("\\", "/")
    return _sw_cache[state]


# kept for old imports
STYLE = ""


def apply_theme(app, mode="dark"):
    c = DARK if mode == "dark" else LIGHT
    C.clear()
    C.update(c)
    _cache.clear()
    app.setStyle("Fusion")
    from . import fonts
    app.setFont(fonts.make(pt=9))
    pal = QPalette()
    q = QColor
    pal.setColor(QPalette.Window, q(c["bg"]))
    pal.setColor(QPalette.WindowText, q(c["text"]))
    pal.setColor(QPalette.Base, q(c["field"]))
    pal.setColor(QPalette.AlternateBase, q(c["panel"]))
    pal.setColor(QPalette.Text, q(c["text"]))
    pal.setColor(QPalette.Button, q(c["panel2"]))
    pal.setColor(QPalette.ButtonText, q(c["text"]))
    pal.setColor(QPalette.ToolTipBase, q(c["panel"]))
    pal.setColor(QPalette.ToolTipText, q(c["text"]))
    pal.setColor(QPalette.Highlight, q(c["accent"]))
    pal.setColor(QPalette.HighlightedText, q("white"))
    pal.setColor(QPalette.Disabled, QPalette.Text, q(c["muted"]))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, q(c["muted"]))
    app.setPalette(pal)
    app.setStyleSheet(build_style(c))


def round_menu(menu):
    """Frameless translucent menu so the QSS border-radius shows."""
    menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WA_TranslucentBackground)
    return menu


def paint_glass(widget, radius, alpha=205, dark=True):
    """Glass surface: translucent fill, top-lit gradient, 1px light stroke."""
    p = QPainter(widget)
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(widget.rect()).adjusted(1, 1, -1, -1)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(24, 24, 30, alpha) if dark else QColor(250, 250, 255, alpha))
    p.drawRoundedRect(r, radius, radius)
    g = QLinearGradient(0, r.top(), 0, r.bottom())
    g.setColorAt(0, QColor(255, 255, 255, 46))
    g.setColorAt(0.5, QColor(255, 255, 255, 8))
    g.setColorAt(1, QColor(255, 255, 255, 18))
    p.setBrush(QBrush(g))
    p.drawRoundedRect(r, radius, radius)
    p.setBrush(QBrush(Qt.NoBrush))
    p.setPen(QPen(QColor(255, 255, 255, 56) if dark else QColor(255, 255, 255, 220), 1))
    p.drawRoundedRect(r, radius, radius)


def paint_pill(widget, radius):
    paint_glass(widget, radius)


def glassify(win):
    """Real acrylic blur behind a top-level window (falls back to a solid window)."""
    from . import winutil
    dark = C["mode"] == "dark"
    ok = False
    try:
        win.setAttribute(Qt.WA_TranslucentBackground, True)
        win.winId()
        ok = winutil.enable_acrylic(win, dark)
    except Exception:
        ok = False
    if not ok:
        win.setAttribute(Qt.WA_TranslucentBackground, False)
    win.setProperty("glass", "true" if ok else "false")
    win.style().unpolish(win)
    win.style().polish(win)
    return ok


def _poly(pts):
    return QPolygonF([QPointF(x, y) for x, y in pts])


def _text(p, rect, txt, size, color, bold=True):
    p.setPen(color)
    from . import fonts
    f = fonts.make(px_size=size)
    f.setPixelSize(size)
    f.setBold(bold)
    p.setFont(f)
    p.drawText(rect, Qt.AlignCenter, txt)


def _draw(p: QPainter, name: str, color: QColor):
    """Draws a 24x24 glyph."""
    fillc = QColor(color)
    if name == "select":
        p.setBrush(fillc)
        p.drawPolygon(_poly([(6, 3), (6, 19), (10.5, 15), (13.5, 21), (16, 20), (13, 14), (19, 14)]))
    elif name == "crop":
        p.drawPolyline(_poly([(7, 3), (7, 17), (21, 17)]))
        p.drawPolyline(_poly([(3, 7), (17, 7), (17, 21)]))
    elif name == "arrow":
        p.drawLine(QPointF(5, 19), QPointF(19, 5))
        p.drawPolyline(_poly([(10, 5), (19, 5), (19, 14)]))
    elif name == "line":
        p.drawLine(QPointF(5, 19), QPointF(19, 5))
    elif name == "rect":
        p.drawRoundedRect(QRectF(4, 6, 16, 12), 3, 3)
    elif name == "ellipse":
        p.drawEllipse(QRectF(3, 5, 18, 14))
    elif name == "pen":
        path = QPainterPath(QPointF(4, 17))
        path.cubicTo(8, 4, 12, 4, 12, 12)
        path.cubicTo(12, 19, 17, 19, 20, 7)
        p.drawPath(path)
    elif name == "highlighter":
        p.setBrush(fillc)
        p.drawPolygon(_poly([(15, 3), (21, 9), (11, 19), (6, 19), (5, 14)]))
        p.drawLine(QPointF(3, 22), QPointF(21, 22))
    elif name == "text":
        p.drawLine(QPointF(5, 6), QPointF(19, 6))
        p.drawLine(QPointF(12, 6), QPointF(12, 19))
        p.drawLine(QPointF(9, 19), QPointF(15, 19))
    elif name == "counter":
        p.drawEllipse(QRectF(3, 3, 18, 18))
        _text(p, QRectF(3, 3, 18, 18), "1", 12, fillc)
    elif name == "pixelate":
        p.setBrush(fillc)
        for i in range(3):
            for j in range(3):
                if (i + j) % 2 == 0:
                    p.drawRect(QRectF(4 + i * 5.4, 4 + j * 5.4, 5.4, 5.4))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(4, 4, 16.2, 16.2), 2, 2)
    elif name == "blur":
        p.drawEllipse(QRectF(3, 3, 18, 18))
        p.setBrush(QColor(fillc.red(), fillc.green(), fillc.blue(), 120))
        p.drawEllipse(QRectF(7, 7, 10, 10))
    elif name == "spotlight":
        path = QPainterPath()
        path.addRoundedRect(QRectF(3, 4, 18, 16), 3, 3)
        hole = QPainterPath()
        hole.addEllipse(QRectF(8, 8, 8, 8))
        p.setBrush(QColor(fillc.red(), fillc.green(), fillc.blue(), 150))
        p.drawPath(path.subtracted(hole))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(8, 8, 8, 8))
    elif name == "eyedrop":
        p.drawPolyline(_poly([(4, 20), (4, 17), (14, 7)]))
        p.drawPolygon(_poly([(14, 7), (17, 4), (20, 7), (17, 10)]))
        p.drawLine(QPointF(4, 20), QPointF(7, 20))
        p.drawLine(QPointF(4, 17), QPointF(10, 11))
    elif name == "rotl":
        path = QPainterPath(QPointF(19, 12))
        path.arcTo(QRectF(5, 6, 14, 14), 0, 270)
        p.drawPath(path)
        p.drawPolyline(_poly([(5, 3), (5, 8), (10, 8)]))
    elif name == "rotr":
        p.translate(24, 0)
        p.scale(-1, 1)
        _draw(p, "rotl", color)
    elif name == "fliph":
        p.drawLine(QPointF(12, 3), QPointF(12, 21))
        p.setBrush(QColor(fillc.red(), fillc.green(), fillc.blue(), 90))
        p.drawPolygon(_poly([(9, 7), (3, 18), (9, 18)]))
        p.drawPolygon(_poly([(15, 7), (21, 18), (15, 18)]))
    elif name == "flipv":
        p.drawLine(QPointF(3, 12), QPointF(21, 12))
        p.setBrush(QColor(fillc.red(), fillc.green(), fillc.blue(), 90))
        p.drawPolygon(_poly([(7, 9), (18, 3), (18, 9)]))
        p.drawPolygon(_poly([(7, 15), (18, 21), (18, 15)]))
    elif name == "resize":
        p.drawRoundedRect(QRectF(3, 8, 13, 13), 2, 2)
        p.drawPolyline(_poly([(13, 3), (21, 3), (21, 11)]))
        p.drawLine(QPointF(21, 3), QPointF(13, 11))
    elif name == "undo":
        p.drawPolyline(_poly([(9, 5), (4, 10), (9, 15)]))
        path = QPainterPath(QPointF(4, 10))
        path.lineTo(14, 10)
        path.arcTo(QRectF(9, 10, 10, 10), 90, -180)
        path.lineTo(8, 20)
        p.drawPath(path)
    elif name == "redo":
        p.translate(24, 0)
        p.scale(-1, 1)
        _draw(p, "undo", color)
    elif name == "copy":
        p.drawRoundedRect(QRectF(8, 8, 12, 12), 3, 3)
        p.drawPolyline(_poly([(4, 16), (4, 6), (6, 4), (16, 4)]))
    elif name == "save":
        p.drawRoundedRect(QRectF(4, 4, 16, 16), 3, 3)
        p.drawRect(QRectF(8, 4, 8, 5))
        p.drawRect(QRectF(7, 14, 10, 6))
    elif name == "pin":
        p.setBrush(fillc)
        p.drawPolygon(_poly([(8, 3), (16, 3), (15, 10), (18, 14), (6, 14), (9, 10)]))
        p.drawLine(QPointF(12, 14), QPointF(12, 21))
    elif name == "folder":
        p.drawRoundedRect(QRectF(3, 6, 18, 13), 3, 3)
        p.drawLine(QPointF(3, 10), QPointF(21, 10))
    elif name == "close":
        p.drawLine(QPointF(6, 6), QPointF(18, 18))
        p.drawLine(QPointF(18, 6), QPointF(6, 18))
    elif name == "edit":
        p.drawPolygon(_poly([(4, 20), (5, 15), (16, 4), (20, 8), (9, 19)]))
    elif name == "area":
        for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            cx, cy = (3 if sx > 0 else 21), (3 if sy > 0 else 21)
            p.drawPolyline(_poly([(cx + sx * 6, cy), (cx, cy), (cx, cy + sy * 6)]))
    elif name == "fullscreen":
        p.drawRoundedRect(QRectF(3, 4, 18, 12), 3, 3)
        p.drawLine(QPointF(8, 20), QPointF(16, 20))
        p.drawLine(QPointF(12, 16), QPointF(12, 20))
    elif name == "window":
        p.drawRoundedRect(QRectF(3, 4, 18, 16), 3, 3)
        p.drawLine(QPointF(3, 9), QPointF(21, 9))
    elif name == "scroll":
        p.drawRoundedRect(QRectF(6, 3, 12, 18), 3, 3)
        p.drawLine(QPointF(12, 8), QPointF(12, 16))
        p.drawPolyline(_poly([(9, 13), (12, 16), (15, 13)]))
    elif name == "timer":
        p.drawEllipse(QRectF(4, 5, 16, 16))
        p.drawLine(QPointF(12, 13), QPointF(12, 9))
        p.drawLine(QPointF(9, 3), QPointF(15, 3))
    elif name == "ocr":
        for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            cx, cy = (3 if sx > 0 else 21), (3 if sy > 0 else 21)
            p.drawPolyline(_poly([(cx + sx * 4, cy), (cx, cy), (cx, cy + sy * 4)]))
        p.drawLine(QPointF(8, 8), QPointF(16, 8))
        p.drawLine(QPointF(12, 8), QPointF(12, 17))
    elif name == "record":
        p.setBrush(QColor("#ff453a"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(5, 5, 14, 14))
    elif name == "gif":
        p.drawRoundedRect(QRectF(2, 5, 20, 14), 4, 4)
        _text(p, QRectF(2, 5, 20, 14), "GIF", 8, fillc)
    elif name == "history":
        p.drawEllipse(QRectF(3, 3, 18, 18))
        p.drawPolyline(_poly([(12, 7), (12, 12), (16, 14)]))
    elif name == "settings":
        p.drawEllipse(QRectF(8, 8, 8, 8))
        for i in range(8):
            a = i * math.pi / 4
            p.drawLine(QPointF(12 + 6 * math.cos(a), 12 + 6 * math.sin(a)), QPointF(12 + 10 * math.cos(a), 12 + 10 * math.sin(a)))
    elif name == "check":
        p.drawPolyline(_poly([(4, 12), (10, 18), (20, 6)]))
    elif name == "trash":
        p.drawRoundedRect(QRectF(6, 8, 12, 13), 2, 2)
        p.drawLine(QPointF(4, 6), QPointF(20, 6))
        p.drawLine(QPointF(10, 3), QPointF(14, 3))
    elif name == "bg":
        p.drawRoundedRect(QRectF(3, 3, 18, 18), 4, 4)
        p.setBrush(fillc)
        p.drawRoundedRect(QRectF(7, 7, 10, 10), 3, 3)
    elif name == "stop":
        p.setBrush(fillc)
        p.drawRoundedRect(QRectF(6, 6, 12, 12), 3, 3)
    elif name == "pause":
        p.setBrush(fillc)
        p.drawRoundedRect(QRectF(7, 5, 3.5, 14), 1.5, 1.5)
        p.drawRoundedRect(QRectF(13.5, 5, 3.5, 14), 1.5, 1.5)
    elif name == "allinone":
        for i in range(2):
            for j in range(2):
                p.drawRoundedRect(QRectF(3 + i * 10, 3 + j * 10, 8, 8), 2.5, 2.5)
    elif name == "open":
        p.drawRoundedRect(QRectF(4, 8, 12, 12), 3, 3)
        p.drawPolyline(_poly([(10, 14), (20, 4)]))
        p.drawPolyline(_poly([(13, 4), (20, 4), (20, 11)]))
    elif name == "camera":
        p.drawRoundedRect(QRectF(3, 7, 18, 13), 4, 4)
        p.drawEllipse(QRectF(8.5, 9.5, 7, 7))
        p.drawLine(QPointF(8, 5), QPointF(16, 5))
    elif name == "moon":
        disc = QPainterPath()
        disc.addEllipse(QRectF(4, 4, 16, 16))
        bite = QPainterPath()
        bite.addEllipse(QRectF(9, 1, 14, 14))
        p.setBrush(fillc)
        p.drawPath(disc.subtracted(bite))
    elif name == "sun":
        p.drawEllipse(QRectF(8, 8, 8, 8))
        for i in range(8):
            a = i * math.pi / 4
            p.drawLine(QPointF(12 + 6.5 * math.cos(a), 12 + 6.5 * math.sin(a)), QPointF(12 + 9.5 * math.cos(a), 12 + 9.5 * math.sin(a)))
    elif name == "project":
        p.drawPolygon(_poly([(5, 3), (14, 3), (19, 8), (19, 21), (5, 21)]))
        p.drawPolyline(_poly([(14, 3), (14, 8), (19, 8)]))
    elif name == "more":
        p.setBrush(fillc)
        for x in (5, 12, 19):
            p.drawEllipse(QRectF(x - 1.6, 10.4, 3.2, 3.2))
    elif name == "image":
        p.drawRoundedRect(QRectF(3, 4, 18, 16), 3, 3)
        p.drawEllipse(QRectF(7, 8, 3, 3))
        p.drawPolyline(_poly([(4, 18), (10, 12), (14, 16), (17, 13), (21, 17)]))
    elif name == "drag":
        for x in (8, 14):
            for y in (6, 12, 18):
                p.setBrush(fillc)
                p.drawEllipse(QRectF(x - 1.3, y - 1.3, 2.6, 2.6))
    elif name == "lock":
        p.drawRoundedRect(QRectF(5, 11, 14, 10), 3, 3)
        p.drawArc(QRectF(8, 3, 8, 12), 0, 180 * 16)
    elif name == "unlock":
        p.drawRoundedRect(QRectF(5, 11, 14, 10), 3, 3)
        p.drawArc(QRectF(8, 3, 8, 12), 0, 140 * 16)
    elif name == "plus":
        p.drawLine(QPointF(12, 5), QPointF(12, 19))
        p.drawLine(QPointF(5, 12), QPointF(19, 12))
    elif name == "info":
        p.drawEllipse(QRectF(3, 3, 18, 18))
        p.drawLine(QPointF(12, 11), QPointF(12, 17))
        p.drawPoint(QPointF(12, 7.5))
    elif name == "restore":
        p.drawPolyline(_poly([(4, 8), (4, 3), (9, 3)]))
        path = QPainterPath(QPointF(4.5, 8))
        path.arcTo(QRectF(4, 4, 16, 16), 150, 280)
        p.drawPath(path)
    elif name == "eye":
        path = QPainterPath(QPointF(2, 12))
        path.quadTo(12, 2, 22, 12)
        path.quadTo(12, 22, 2, 12)
        p.drawPath(path)
        p.drawEllipse(QRectF(9, 9, 6, 6))
    elif name == "palette":
        path = QPainterPath()
        path.moveTo(12, 3)
        path.cubicTo(5.5, 3, 2.5, 7.5, 2.5, 12)
        path.cubicTo(2.5, 17, 7, 21, 12, 21)
        path.cubicTo(14, 21, 14.6, 19.6, 13.8, 18.2)
        path.cubicTo(13, 16.8, 13.8, 15.4, 15.6, 15.4)
        path.lineTo(18, 15.4)
        path.cubicTo(20, 15.4, 21.5, 14, 21.5, 12)
        path.cubicTo(21.5, 7, 17.5, 3, 12, 3)
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        for (x, y, col) in ((7.2, 11, "#ff453a"), (9.6, 7, "#ffd60a"), (14.4, 7, "#30d158"), (17, 11, "#0a84ff")):
            p.setBrush(QColor(col))
            p.drawEllipse(QRectF(x - 1.5, y - 1.5, 3, 3))
    elif name == "grid":
        for i in range(3):
            for j in range(3):
                p.drawRoundedRect(QRectF(3 + i * 6.5, 3 + j * 6.5, 4.5, 4.5), 1, 1)


_cache = {}


def icon(name: str, color: str = None, size: int = 56) -> QIcon:
    color = color or C["text"]
    key = (name, color, size)
    if key in _cache:
        return _cache[key]
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    p.scale(size / 24.0, size / 24.0)
    c = QColor(color)
    p.setPen(QPen(c, 1.9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    _draw(p, name, c)
    p.end()
    ic = QIcon(pm)
    _cache[key] = ic
    return ic


def app_icon() -> QIcon:
    """프로젝트 루트의 icon.png를 사용하고, 없으면 기본 아이콘을 그린다."""
    import os
    from PyQt5.QtGui import QImage
    from .paths import res
    path = res("icon.png")
    if os.path.exists(path):
        img = QImage(path)
        if not img.isNull():
            ic = QIcon()
            for sz in (16, 24, 32, 48, 64, 128, 256):
                ic.addPixmap(QPixmap.fromImage(img.scaled(sz, sz, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            return ic
    return _default_icon()


def _default_icon() -> QIcon:
    size = 256
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHints(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor("#3ab0ff"))
    g.setColorAt(1, QColor("#5b3bff"))
    p.setBrush(QBrush(g))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 64, 64)
    p.setPen(QPen(QColor("white"), 16, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    m, l = 60, 40
    for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        cx, cy = (m if sx > 0 else size - m), (m if sy > 0 else size - m)
        p.drawPolyline(_poly([(cx + sx * l, cy), (cx, cy), (cx, cy + sy * l)]))
    p.setBrush(QColor("white"))
    p.setPen(Qt.NoPen)
    p.drawEllipse(QRectF(98, 98, 60, 60))
    p.end()
    return QIcon(pm)
