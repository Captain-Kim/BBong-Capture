"""Annotation items for the editor. Every item can serialise itself (project files, undo of edits)."""
import math
import random

import cv2
import numpy as np
from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPainterPathStroker, QPen,
                         QPolygonF, QTextCharFormat, QTextCursor)
from PyQt5.QtWidgets import (QGraphicsDropShadowEffect, QGraphicsItem, QGraphicsPathItem, QGraphicsPixmapItem,
                             QGraphicsTextItem)

from . import fonts as _fonts
from . import imgutil

ARROW_STYLES = ["테이퍼", "라인", "곡선", "양방향"]
TEXT_STYLES = ["기본", "굵게", "외곽선", "배경 상자", "라운드 라벨", "그림자", "형광 배경"]
REDACT_MODES = {"pixelate": "모자이크", "blur": "블러 (부드럽게)", "secure": "블러 (보안)"}


def _pt(p):
    return [round(p.x(), 2), round(p.y(), 2)]


def _P(a):
    return QPointF(a[0], a[1])


def _sel_outline(item, painter, rect=None):
    if item.isSelected():
        pen = QPen(QColor(10, 132, 255), 1, Qt.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect if rect is not None else item.boundingRect())


def _lum(c: QColor):
    return 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()


class Ann:
    """Mixin: common API used by the editor."""
    kind = "ann"
    has_color = True

    def common(self):
        return {"kind": self.kind, "pos": _pt(self.pos())}

    def set_color(self, col: QColor):
        pass

    def handles(self):
        """[(name, scene QPointF)]"""
        return []

    def drag_handle(self, name, scene_pos):
        pass


# ----------------------------------------------------------------------------- arrow
class ArrowItem(Ann, QGraphicsPathItem):
    kind = "arrow"

    def __init__(self, p1, p2, color="#ff453a", width=5, style=0, ctrl=None):
        super().__init__()
        self.color, self.w, self.style = QColor(color), width, style
        self.p1, self.p2 = QPointF(p1), QPointF(p2)
        self.ctrl = QPointF(ctrl) if ctrl is not None else None
        self.setBrush(self.color)
        self.setPen(QPen(Qt.NoPen))
        self.rebuild()

    def set_end(self, p2):
        self.p2 = QPointF(p2)
        if self.style == 2:
            self.ctrl = None
        self.rebuild()

    def _control(self):
        if self.ctrl is not None:
            return self.ctrl
        mid = (self.p1 + self.p2) / 2
        d = self.p2 - self.p1
        L = math.hypot(d.x(), d.y()) or 1
        return QPointF(mid.x() - d.y() / L * L * 0.28, mid.y() + d.x() / L * L * 0.28)

    @staticmethod
    def _head(tip, direction, size, half):
        L = math.hypot(direction.x(), direction.y()) or 1
        ux, uy = direction.x() / L, direction.y() / L
        base = QPointF(tip.x() - ux * size, tip.y() - uy * size)
        n = QPointF(-uy, ux)
        return base, QPolygonF([tip, base + n * half, base - n * half])

    def rebuild(self):
        self.prepareGeometryChange()
        d = self.p2 - self.p1
        L = math.hypot(d.x(), d.y())
        path = QPainterPath()
        if L < 2:
            self.setPath(path)
            return
        w = self.w
        hl = min(L * 0.9, max(w * 4.2, 16))
        hw = max(w * 2.2, 8)
        ux, uy = d.x() / L, d.y() / L
        nrm = QPointF(-uy, ux)

        def stroke(p: QPainterPath, width):
            st = QPainterPathStroker()
            st.setWidth(width)
            st.setCapStyle(Qt.RoundCap)
            st.setJoinStyle(Qt.RoundJoin)
            return st.createStroke(p)

        if self.style == 0:     # tapered
            b = QPointF(self.p2.x() - ux * hl, self.p2.y() - uy * hl)
            s0, s1 = w * 0.18, w * 0.62
            path.addPolygon(QPolygonF([self.p1 + nrm * s0, b + nrm * s1, b + nrm * hw, self.p2, b - nrm * hw,
                                       b - nrm * s1, self.p1 - nrm * s0]))
            path.closeSubpath()
        elif self.style == 1:   # line with open head
            line = QPainterPath(self.p1)
            line.lineTo(self.p2)
            ang = math.atan2(uy, ux)
            for s in (-1, 1):
                a = ang + math.pi + s * math.radians(28)
                line.moveTo(self.p2)
                line.lineTo(QPointF(self.p2.x() + math.cos(a) * hl, self.p2.y() + math.sin(a) * hl))
            path = stroke(line, w)
        elif self.style == 2:   # curved
            c = self._control()
            base, head = self._head(self.p2, self.p2 - c, hl, hw * 0.8)
            curve = QPainterPath(self.p1)
            curve.quadTo(c, base)
            path = stroke(curve, w)
            path.addPolygon(head)
        else:                   # double-headed
            b1, h1 = self._head(self.p2, d, hl, hw * 0.8)
            b2, h2 = self._head(self.p1, -d, hl, hw * 0.8)
            line = QPainterPath(b2)
            line.lineTo(b1)
            path = stroke(line, w)
            path.addPolygon(h1)
            path.addPolygon(h2)
        self.setPath(path)

    def paint(self, painter, opt, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        super().paint(painter, opt, widget)
        _sel_outline(self, painter)

    def set_color(self, col):
        self.color = QColor(col)
        self.setBrush(self.color)

    def handles(self):
        h = [("p1", self.mapToScene(self.p1)), ("p2", self.mapToScene(self.p2))]
        if self.style == 2:
            h.append(("c", self.mapToScene(self._control())))
        return h

    def drag_handle(self, name, sp):
        p = self.mapFromScene(sp)
        if name == "p1":
            self.p1 = p
        elif name == "p2":
            self.p2 = p
        else:
            self.ctrl = p
        self.rebuild()

    def to_dict(self):
        d = self.common()
        d.update(p1=_pt(self.p1), p2=_pt(self.p2), color=self.color.name(), w=self.w, style=self.style,
                 ctrl=_pt(self.ctrl) if self.ctrl is not None else None)
        return d

    def apply(self, d):
        self.setPos(_P(d["pos"]))
        self.p1, self.p2 = _P(d["p1"]), _P(d["p2"])
        self.ctrl = _P(d["ctrl"]) if d.get("ctrl") else None
        self.color, self.w, self.style = QColor(d["color"]), d["w"], d["style"]
        self.setBrush(self.color)
        self.rebuild()

    @staticmethod
    def from_dict(d, ed=None):
        it = ArrowItem(_P(d["p1"]), _P(d["p2"]))
        it.apply(d)
        return it


# ----------------------------------------------------------------------------- line / rect / ellipse
class _Shape(Ann):
    def common_shape(self):
        d = self.common()
        pen = self.pen()
        filled = hasattr(self, "brush") and self.brush().style() != Qt.NoBrush     # lines have no brush
        d.update(color=pen.color().name(), w=pen.widthF(), fill=filled)
        return d

    def set_color(self, col):
        pen = self.pen()
        pen.setColor(QColor(col))
        self.setPen(pen)
        if hasattr(self, "brush") and self.brush().style() != Qt.NoBrush:
            fc = QColor(col)
            fc.setAlpha(110)
            self.setBrush(fc)

    def _apply_style(self, d):
        self.setPos(_P(d["pos"]))
        pen = self.pen()
        pen.setColor(QColor(d["color"]))
        pen.setWidthF(d["w"])
        self.setPen(pen)
        if not hasattr(self, "setBrush"):
            return
        if d.get("fill"):
            fc = QColor(d["color"])
            fc.setAlpha(110)
            self.setBrush(fc)
        else:
            self.setBrush(QBrush(Qt.NoBrush))


from PyQt5.QtWidgets import QGraphicsEllipseItem, QGraphicsLineItem, QGraphicsRectItem  # noqa: E402


class LineItem(_Shape, QGraphicsLineItem):
    kind = "line"

    def paint(self, painter, opt, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        super().paint(painter, opt, widget)

    def handles(self):
        l = self.line()
        return [("p1", self.mapToScene(l.p1())), ("p2", self.mapToScene(l.p2()))]

    def drag_handle(self, name, sp):
        p = self.mapFromScene(sp)
        l = self.line()
        if name == "p1":
            self.setLine(p.x(), p.y(), l.x2(), l.y2())
        else:
            self.setLine(l.x1(), l.y1(), p.x(), p.y())

    def to_dict(self):
        d = self.common_shape()
        l = self.line()
        d["line"] = [l.x1(), l.y1(), l.x2(), l.y2()]
        return d

    def apply(self, d):
        self.setLine(*d["line"])
        self._apply_style(d)

    @staticmethod
    def from_dict(d, ed=None):
        it = LineItem(*d["line"])
        it.apply(d)
        return it


class RectGeom:
    """Handle support for rect-based items."""

    def geom(self):
        return self.rect()

    def set_geom(self, r):
        self.prepareGeometryChange()
        self.setRect(r)

    def handles(self):
        r = self.geom()
        pts = {"tl": r.topLeft(), "t": QPointF(r.center().x(), r.top()), "tr": r.topRight(),
               "l": QPointF(r.left(), r.center().y()), "r": QPointF(r.right(), r.center().y()),
               "bl": r.bottomLeft(), "b": QPointF(r.center().x(), r.bottom()), "br": r.bottomRight()}
        return [(k, self.mapToScene(v)) for k, v in pts.items()]

    def drag_handle(self, name, sp):
        p = self.mapFromScene(sp)
        r = QRectF(self.geom())
        if "l" in name:
            r.setLeft(p.x())
        if "r" in name:
            r.setRight(p.x())
        if name.startswith("t"):
            r.setTop(p.y())
        if name.startswith("b"):
            r.setBottom(p.y())
        self.set_geom(r.normalized())


class RectItem(RectGeom, _Shape, QGraphicsRectItem):
    kind = "rect"
    radius = 0

    def paint(self, painter, opt, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        painter.drawRoundedRect(self.rect(), self.radius, self.radius)
        _sel_outline(self, painter, self.rect())

    def to_dict(self):
        d = self.common_shape()
        r = self.rect()
        d.update(rect=[r.x(), r.y(), r.width(), r.height()], radius=self.radius)
        return d

    def apply(self, d):
        self.setRect(QRectF(*d["rect"]))
        self.radius = d.get("radius", 0)
        self._apply_style(d)

    @staticmethod
    def from_dict(d, ed=None):
        it = RectItem(QRectF(*d["rect"]))
        it.apply(d)
        return it


class EllipseItem(RectGeom, _Shape, QGraphicsEllipseItem):
    kind = "ellipse"

    def paint(self, painter, opt, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        painter.drawEllipse(self.rect())
        _sel_outline(self, painter, self.rect())

    def to_dict(self):
        d = self.common_shape()
        r = self.rect()
        d["rect"] = [r.x(), r.y(), r.width(), r.height()]
        return d

    def apply(self, d):
        self.setRect(QRectF(*d["rect"]))
        self._apply_style(d)

    @staticmethod
    def from_dict(d, ed=None):
        it = EllipseItem(QRectF(*d["rect"]))
        it.apply(d)
        return it


# ----------------------------------------------------------------------------- pen / highlighter
def smooth_path(points):
    path = QPainterPath()
    if not points:
        return path
    path.moveTo(points[0])
    if len(points) < 3:
        for p in points[1:]:
            path.lineTo(p)
        if len(points) == 1:
            path.lineTo(points[0] + QPointF(0.01, 0.01))
        return path
    for i in range(1, len(points) - 1):
        mid = (points[i] + points[i + 1]) / 2
        path.quadTo(points[i], mid)
    path.lineTo(points[-1])
    return path


class PenItem(Ann, QGraphicsPathItem):
    kind = "pen"

    def __init__(self, start, color="#ff453a", width=5, highlighter=False):
        super().__init__()
        self.highlighter = highlighter
        self.kind = "highlighter" if highlighter else "pen"
        self.color, self.w = QColor(color), width
        self.points = [QPointF(start)]
        self._style()
        self.setPath(smooth_path(self.points))

    def _style(self):
        c = QColor(self.color)
        if self.highlighter:
            c.setAlpha(105)
            self.setPen(QPen(c, self.w * 4.5 if not getattr(self, "fixed_h", None) else self.fixed_h, Qt.SolidLine,
                             Qt.FlatCap, Qt.RoundJoin))
        else:
            self.setPen(QPen(c, self.w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

    def add_point(self, pt):
        if (pt - self.points[-1]).manhattanLength() < 1.5:
            return
        self.prepareGeometryChange()
        self.points.append(QPointF(pt))
        self.setPath(smooth_path(self.points))

    def make_straight(self, thickness=None, y=None):
        """Highlighter: snap to a straight band (used by smart text-size detection)."""
        a, b = self.points[0], self.points[-1]
        yy = y if y is not None else (a.y() + b.y()) / 2
        self.points = [QPointF(a.x(), yy), QPointF(b.x(), yy)]
        if thickness:
            self.fixed_h = thickness
        self._style()
        self.prepareGeometryChange()
        self.setPath(smooth_path(self.points))

    def paint(self, painter, opt, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        if self.highlighter:
            painter.setCompositionMode(QPainter.CompositionMode_Multiply)
        super().paint(painter, opt, widget)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        _sel_outline(self, painter)

    def set_color(self, col):
        self.color = QColor(col)
        self._style()

    def to_dict(self):
        d = self.common()
        d.update(points=[_pt(p) for p in self.points], color=self.color.name(), w=self.w, hl=self.highlighter,
                 fixed_h=getattr(self, "fixed_h", None))
        return d

    def apply(self, d):
        self.setPos(_P(d["pos"]))
        self.color, self.w = QColor(d["color"]), d["w"]
        self.fixed_h = d.get("fixed_h")
        self.points = [_P(p) for p in d["points"]]
        self._style()
        self.setPath(smooth_path(self.points))

    @staticmethod
    def from_dict(d, ed=None):
        it = PenItem(_P(d["points"][0]), d["color"], d["w"], d.get("hl", False))
        it.apply(d)
        return it


# ----------------------------------------------------------------------------- counter
class CounterItem(Ann, QGraphicsEllipseItem):
    kind = "counter"

    def __init__(self, center, number, color="#ff453a", width=5):
        r = 11 + width * 1.6
        super().__init__(-r, -r, 2 * r, 2 * r)
        self.number, self.r, self.w = number, r, width
        self.color = QColor(color)
        self.setPos(center)
        self.setPen(QPen(QColor("white"), max(1.5, width * 0.35)))
        self.setBrush(self.color)

    def paint(self, painter, opt, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        painter.drawEllipse(self.rect())
        painter.setPen(QColor("#1c1c1e") if _lum(self.color) > 170 else QColor("white"))
        f = QFont(_fonts.family())
        f.setBold(True)
        f.setPixelSize(int(self.r * 1.1))
        painter.setFont(f)
        painter.drawText(self.rect(), Qt.AlignCenter, str(self.number))
        _sel_outline(self, painter)

    def set_color(self, col):
        self.color = QColor(col)
        self.setBrush(self.color)

    def to_dict(self):
        d = self.common()
        d.update(number=self.number, color=self.color.name(), w=self.w)
        return d

    def apply(self, d):
        self.setPos(_P(d["pos"]))
        self.number = d["number"]
        self.set_color(d["color"])
        self.update()

    @staticmethod
    def from_dict(d, ed=None):
        it = CounterItem(_P(d["pos"]), d["number"], d["color"], d["w"])
        it.apply(d)
        return it


# ----------------------------------------------------------------------------- text (7 styles)
class TextItem(Ann, QGraphicsTextItem):
    kind = "text"

    def __init__(self, pos, color="#ff453a", width=5, on_empty=None, style=0, family=None):
        super().__init__()
        self.on_empty = on_empty
        self.family = family or _fonts.family()
        self.color, self.w, self.style = QColor(color), width, style
        self.setPos(pos)
        self.setTextInteractionFlags(Qt.TextEditorInteraction)
        self.setFlag(QGraphicsItem.ItemIsFocusable, True)
        self.document().setDocumentMargin(8)
        self.apply_style()

    def apply_style(self):
        f = QFont(self.family)
        f.setPixelSize(int(16 + self.w * 2.4))
        f.setBold(self.style != 0)
        self.setFont(f)
        label = self.style in (3, 4)
        textc = self.color
        if label:
            textc = QColor("#1c1c1e") if _lum(self.color) > 170 else QColor("white")
        elif self.style == 6:
            textc = QColor("#1c1c1e")
        elif self.style == 2:      # contrasting fill, outlined in the chosen colour (readable on any background)
            textc = QColor("#ffffff") if _lum(self.color) < 170 else QColor("#1c1c1e")
        self.setDefaultTextColor(textc)
        cur = QTextCursor(self.document())
        cur.select(QTextCursor.Document)
        fmt = QTextCharFormat()
        fmt.setForeground(textc)
        if self.style == 2:
            fmt.setTextOutline(QPen(self.color, 2.2))
        else:
            fmt.setTextOutline(QPen(Qt.NoPen))
        cur.mergeCharFormat(fmt)
        if self.style == 5:
            eff = QGraphicsDropShadowEffect()
            eff.setBlurRadius(8)
            eff.setOffset(2, 3)
            eff.setColor(QColor(0, 0, 0, 190))
            self.setGraphicsEffect(eff)
        else:
            self.setGraphicsEffect(None)
        self.update()

    def set_color(self, col):
        self.color = QColor(col)
        self.apply_style()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        c = self.textCursor()
        c.clearSelection()
        self.setTextCursor(c)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        if not self.toPlainText().strip() and self.on_empty:
            self.on_empty(self)

    def mouseDoubleClickEvent(self, e):
        self.setTextInteractionFlags(Qt.TextEditorInteraction)
        self.setFocus()
        super().mouseDoubleClickEvent(e)

    def paint(self, painter, opt, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        r = self.boundingRect()
        if self.style in (3, 4):
            painter.setPen(Qt.NoPen)
            painter.setBrush(self.color)
            painter.drawRoundedRect(r.adjusted(1, 1, -1, -1), r.height() / 2 if self.style == 4 and r.height() < 60 else 12,
                                    r.height() / 2 if self.style == 4 and r.height() < 60 else 12)
        elif self.style == 6:
            c = QColor(self.color)
            c.setAlpha(140)
            painter.setPen(Qt.NoPen)
            painter.setBrush(c)
            painter.drawRoundedRect(r.adjusted(2, 4, -2, -4), 6, 6)
        opt.state &= ~0x00008000
        opt.state &= ~0x00000002
        super().paint(painter, opt, widget)
        _sel_outline(self, painter)

    def to_dict(self):
        d = self.common()
        d.update(text=self.toPlainText(), color=self.color.name(), w=self.w, style=self.style, family=self.family)
        return d

    def apply(self, d):
        self.setPos(_P(d["pos"]))
        self.color, self.w, self.style = QColor(d["color"]), d["w"], d["style"]
        self.family = d.get("family") or _fonts.family()
        if self.toPlainText() != d["text"]:
            self.setPlainText(d["text"])
        self.apply_style()

    @staticmethod
    def from_dict(d, ed=None):
        it = TextItem(_P(d["pos"]), d["color"], d["w"], ed.remove_empty_text if ed else None, d["style"], d.get("family"))
        it.setPlainText(d["text"])
        it.apply_style()
        it.setTextInteractionFlags(Qt.NoTextInteraction)
        return it


# ----------------------------------------------------------------------------- pixelate / blur (on the base image)
class RedactItem(RectGeom, Ann, QGraphicsRectItem):
    has_color = False

    def __init__(self, rect, mode, editor, seed=None):
        super().__init__(rect)
        self.mode = mode
        self.kind = mode
        self.editor = editor
        self.seed = seed if seed is not None else random.randint(1, 10 ** 6)
        self.setPen(QPen(Qt.NoPen))
        self._cache = None
        self._key = None

    def _render(self):
        base = self.editor.base_image
        r = self.rect().normalized().toAlignedRect().intersected(base.rect())
        if r.width() < 2 or r.height() < 2:
            return None
        key = (r.x(), r.y(), r.width(), r.height(), self.mode, id(base), self.seed)
        if key == self._key:
            return self._cache
        arr = imgutil.to_rgb(base.copy(r))
        rng = np.random.RandomState(self.seed)
        w, h = r.width(), r.height()
        if self.mode in ("pixelate", "secure"):
            block = max(8, int(min(w, h) / (6 if self.mode == "secure" else 9)), 8)
            small = cv2.resize(arr, (max(1, w // block), max(1, h // block)), interpolation=cv2.INTER_AREA).astype(np.int16)
            small += rng.randint(-14, 15, small.shape).astype(np.int16)      # randomisation: blocks are not reversible
            small = np.clip(small, 0, 255).astype(np.uint8)
            arr = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
            if self.mode == "secure":
                k = max(9, (min(w, h) // 3) | 1)
                arr = cv2.GaussianBlur(arr, (k, k), 0)
        else:
            k = max(9, (min(w, h) // 4) | 1)
            arr = cv2.GaussianBlur(cv2.GaussianBlur(arr, (k, k), 0), (k, k), 0)
        img = imgutil.from_rgb(arr)
        self._cache, self._key = (img, r), key
        return self._cache

    def paint(self, painter, opt, widget=None):
        res = self._render()
        if res:
            painter.drawImage(res[1].topLeft(), res[0])
        _sel_outline(self, painter, self.rect())

    def to_dict(self):
        d = self.common()
        r = self.rect()
        d.update(rect=[r.x(), r.y(), r.width(), r.height()], mode=self.mode, seed=self.seed)
        return d

    def apply(self, d):
        self.setPos(_P(d["pos"]))
        self.setRect(QRectF(*d["rect"]))
        self.mode = self.kind = d["mode"]
        self.seed = d["seed"]
        self._key = None
        self.update()

    @staticmethod
    def from_dict(d, ed=None):
        it = RedactItem(QRectF(*d["rect"]), d["mode"], ed, d["seed"])
        it.apply(d)
        return it


# ----------------------------------------------------------------------------- spotlight
class SpotlightItem(RectGeom, Ann, QGraphicsRectItem):
    kind = "spotlight"
    has_color = False

    def __init__(self, rect, editor):
        super().__init__(rect)
        self.editor = editor
        self.setPen(QPen(Qt.NoPen))
        self.setZValue(0.5)

    def boundingRect(self):
        return self.editor.scene.sceneRect().translated(-self.pos())

    def shape(self):
        p = QPainterPath()
        p.addRect(self.rect())
        return p

    def paint(self, painter, opt, widget=None):
        spots = [i for i in self.editor.scene.items() if isinstance(i, SpotlightItem)]
        spots.sort(key=lambda i: id(i))
        if spots and spots[0] is self:      # a single item paints the shared dimming layer
            full = QPainterPath()
            full.addRect(QRectF(self.editor.base_image.rect()))
            for s in spots:
                hole = QPainterPath()
                hole.addRoundedRect(s.rect().translated(s.pos()), 6, 6)
                full = full.subtracted(hole)
            painter.save()
            painter.translate(-self.pos())
            painter.fillPath(full, QColor(0, 0, 0, 150))
            painter.restore()
        if self.isSelected():
            pen = QPen(QColor(10, 132, 255), 1, Qt.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(self.rect(), 6, 6)

    def set_geom(self, r):
        self.prepareGeometryChange()
        self.setRect(r)
        self.editor.scene.update()

    def to_dict(self):
        d = self.common()
        r = self.rect()
        d["rect"] = [r.x(), r.y(), r.width(), r.height()]
        return d

    def apply(self, d):
        self.setPos(_P(d["pos"]))
        self.setRect(QRectF(*d["rect"]))
        self.editor.scene.update()

    @staticmethod
    def from_dict(d, ed=None):
        it = SpotlightItem(QRectF(*d["rect"]), ed)
        it.apply(d)
        return it


# ----------------------------------------------------------------------------- inserted image (combine screenshots)
class ImageItem(RectGeom, Ann, QGraphicsRectItem):
    kind = "image"
    has_color = False

    def __init__(self, image: QImage, pos=QPointF(0, 0), width=None, sticker=False):
        w = width or image.width()
        h = w * image.height() / max(1, image.width())
        super().__init__(QRectF(0, 0, w, h))
        self.image = image
        self.sticker = sticker       # 스티커: 둥근 모서리 · 테두리 없이 투명 배경 그대로
        self.opacity_ = 1.0          # 0.1 ~ 1.0
        self.setPos(pos)
        self.setPen(QPen(Qt.NoPen))

    def paint(self, painter, opt, widget=None):
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        r = self.rect()
        painter.save()
        painter.setOpacity(painter.opacity() * self.opacity_)
        if self.sticker:
            painter.drawImage(r, self.image)
            painter.restore()
            _sel_outline(self, painter, r)
            return
        path = QPainterPath()
        path.addRoundedRect(r, 8, 8)
        painter.setClipPath(path)
        painter.drawImage(r, self.image)
        painter.restore()
        pen = QPen(QColor(255, 255, 255, 60), 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(r, 8, 8)
        _sel_outline(self, painter, r)

    def drag_handle(self, name, sp):      # keep aspect ratio
        r0 = QRectF(self.rect())
        super().drag_handle(name, sp)
        r = self.rect()
        ratio = self.image.height() / max(1, self.image.width())
        w = max(20, r.width())
        nr = QRectF(r.x(), r.y(), w, w * ratio)
        if "l" in name:
            nr.moveRight(r0.right())
        if name.startswith("t"):
            nr.moveBottom(r0.bottom())
        self.setRect(nr)

    def to_dict(self):
        d = self.common()
        r = self.rect()
        d.update(rect=[r.x(), r.y(), r.width(), r.height()], png=imgutil.to_b64(self.image),
                 sticker=self.sticker, opacity=self.opacity_)
        return d

    def apply(self, d):
        self.setPos(_P(d["pos"]))
        self.setRect(QRectF(*d["rect"]))
        self.sticker = d.get("sticker", self.sticker)
        self.opacity_ = d.get("opacity", 1.0)
        self.update()

    @staticmethod
    def from_dict(d, ed=None):
        it = ImageItem(imgutil.from_b64(d["png"]), sticker=d.get("sticker", False))
        it.apply(d)
        return it


FACTORIES = {"arrow": ArrowItem, "line": LineItem, "rect": RectItem, "ellipse": EllipseItem, "pen": PenItem,
             "highlighter": PenItem, "counter": CounterItem, "text": TextItem, "pixelate": RedactItem,
             "blur": RedactItem, "secure": RedactItem, "spotlight": SpotlightItem, "image": ImageItem}


def item_from_dict(d, editor):
    return FACTORIES[d["kind"]].from_dict(d, editor)


def is_ann(item):
    return isinstance(item, Ann)


# ----------------------------------------------------------------------------- base image / background / handles
class BaseItem(QGraphicsPixmapItem):
    def __init__(self, pix):
        super().__init__(pix)
        self.radius = 0

    def paint(self, painter, opt, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if self.radius:
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.pixmap().rect()), self.radius, self.radius)
            painter.setClipPath(path)
        painter.drawPixmap(0, 0, self.pixmap())


class BackgroundItem(QGraphicsRectItem):
    def __init__(self):
        super().__init__()
        self.spec = None
        self.setPen(QPen(Qt.NoPen))

    def paint(self, painter, opt, widget=None):
        from .background import paint_background
        if self.spec is not None and self.spec.kind in ("gradient", "solid", "image", "wallpaper"):
            painter.setRenderHint(QPainter.Antialiasing)
            paint_background(painter, self.rect(), self.spec)


class HandlesItem(QGraphicsItem):
    """Resize / edit handles around the selected annotation."""

    def __init__(self, editor):
        super().__init__()
        self.ed = editor
        self.target = None
        self.active = None
        self.before = None
        self.setZValue(9000)
        self.setAcceptHoverEvents(True)

    def set_target(self, item):
        self.prepareGeometryChange()
        self.target = item
        self.setVisible(item is not None and bool(item.handles()))
        self.update()

    def boundingRect(self):
        return self.ed.scene.sceneRect().adjusted(-40, -40, 40, 40)

    def shape(self):
        p = QPainterPath()
        if self.target is not None:
            s = self._hs()
            for _, pt in self.target.handles():
                p.addRect(QRectF(pt.x() - s, pt.y() - s, 2 * s, 2 * s))
        return p

    def _hs(self):
        return 8 / max(0.05, self.ed.view.scale_factor)

    def _hit(self, pos):
        if self.target is None:
            return None
        s = self._hs()
        for name, pt in self.target.handles():
            if abs(pos.x() - pt.x()) <= s and abs(pos.y() - pt.y()) <= s:
                return name
        return None

    def paint(self, p, opt, widget=None):
        if self.target is None:
            return
        s = self._hs() / 2 * 1.15
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(10, 132, 255), 1.4)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(QColor("white"))
        for name, pt in self.target.handles():
            if name == "c":
                p.drawEllipse(pt, s, s)
            else:
                p.drawRoundedRect(QRectF(pt.x() - s, pt.y() - s, 2 * s, 2 * s), s * 0.4, s * 0.4)

    def mousePressEvent(self, e):
        self.active = self._hit(e.pos())
        if self.active is None:
            e.ignore()
            return
        self.before = self.target.to_dict()
        e.accept()

    def mouseMoveEvent(self, e):
        if self.active and self.target is not None:
            self.target.drag_handle(self.active, e.pos())
            self.target.update()
            self.ed.scene.update()
            self.update()

    def mouseReleaseEvent(self, e):
        if self.active and self.target is not None:
            self.ed.push_state(self.target, self.before, self.target.to_dict())
        self.active = None

    def hoverMoveEvent(self, e):
        self.setCursor(Qt.CrossCursor if self._hit(e.pos()) else Qt.ArrowCursor)
