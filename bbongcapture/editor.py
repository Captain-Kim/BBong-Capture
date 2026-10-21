"""Annotation editor: rounded UI, rich tools, background tool, project files."""
import json
import math
import os
import tempfile

import numpy as np
from PyQt5.QtCore import (QEasingCurve, QMimeData, QPoint, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer, QUrl,
                          pyqtSignal)
from PyQt5.QtGui import (QBrush, QColor, QCursor, QDrag, QFont, QIcon, QImage, QKeySequence, QPainter, QPainterPath, QPen, QPixmap,
                         QTransform)
from PyQt5.QtWidgets import (QAction, QActionGroup, QApplication, QCheckBox, QColorDialog, QComboBox, QDialog,
                             QDoubleSpinBox, QFileDialog, QFrame, QGraphicsDropShadowEffect, QGraphicsItem,
                             QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QMainWindow, QMenu, QPushButton,
                             QSlider, QSpinBox, QToolButton, QUndoCommand, QUndoStack, QVBoxLayout, QWidget)

from . import fonts, imgutil, winutil
from .background import BgSpec, layout
from .bgpanel import BackgroundPanel
from .items import (ARROW_STYLES, REDACT_MODES, TEXT_STYLES, ArrowItem, BackgroundItem, BaseItem, CounterItem,
                    EllipseItem, HandlesItem, ImageItem, LineItem, PenItem, RectItem, RedactItem, SpotlightItem,
                    TextItem, is_ann, item_from_dict)
from .settings import settings
from .theme import C, apply_theme, glassify, icon, px, round_menu

PALETTE = ["#ff453a", "#ff9f0a", "#ffd60a", "#30d158", "#0a84ff", "#bf5af2", "#ffffff", "#1c1c1e"]
Z_BG, Z_BASE = -2000, -1000
CROP_RATIOS = {"자유": None, "원본": "orig", "1:1": 1.0, "4:3": 4 / 3, "3:2": 3 / 2, "16:9": 16 / 9, "3:4": 3 / 4,
               "2:3": 2 / 3, "9:16": 9 / 16}


# ----------------------------------------------------------------------------- undo commands
class AddCmd(QUndoCommand):
    def __init__(self, scene, item):
        super().__init__("추가")
        self.scene, self.item = scene, item

    def redo(self):
        if self.item.scene() is None:
            self.scene.addItem(self.item)

    def undo(self):
        self.scene.removeItem(self.item)


class RemoveCmd(QUndoCommand):
    def __init__(self, scene, items):
        super().__init__("삭제")
        self.scene, self.items = scene, items

    def redo(self):
        for i in self.items:
            self.scene.removeItem(i)

    def undo(self):
        for i in self.items:
            self.scene.addItem(i)


class StateCmd(QUndoCommand):
    """Move / resize / restyle of one item."""

    def __init__(self, item, old, new):
        super().__init__("편집")
        self.item, self.old, self.new, self.first = item, old, new, True

    def redo(self):
        if self.first:
            self.first = False
            return
        self.item.apply(self.new)
        if self.item.scene():
            self.item.scene().update()

    def undo(self):
        self.item.apply(self.old)
        if self.item.scene():
            self.item.scene().update()


def transform_image(img, op, arg=None):
    if op == "rotl":
        return img.transformed(QTransform().rotate(-90), Qt.SmoothTransformation)
    if op == "rotr":
        return img.transformed(QTransform().rotate(90), Qt.SmoothTransformation)
    if op == "fliph":
        return img.mirrored(True, False)
    if op == "flipv":
        return img.mirrored(False, True)
    if op == "resize":
        return img.scaled(arg[0], arg[1], Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    if op == "crop":
        return img.copy(arg)
    return img


class TransformCmd(QUndoCommand):
    """Rotate / flip / resize / crop. Annotations are baked into the image first (undo restores them)."""
    NAMES = {"rotl": "왼쪽으로 회전", "rotr": "오른쪽으로 회전", "fliph": "좌우 반전", "flipv": "상하 반전",
             "resize": "크기 조정", "crop": "크롭"}

    def __init__(self, ed, op, arg=None):
        super().__init__(self.NAMES.get(op, op))
        self.ed, self.op, self.arg = ed, op, arg
        self.old_img = ed.base_image
        self.removed = []
        self.shifted = []

    def redo(self):
        ed = self.ed
        if self.op == "crop":
            # keep annotations live: shift them instead of baking
            self.removed = []
            ed.set_base(transform_image(self.old_img, "crop", self.arg))
            self.shifted = ed.annotation_items()
            for it in self.shifted:
                it.setPos(it.pos() - QPointF(self.arg.x(), self.arg.y()))
            return
        self.removed = ed.annotation_items()
        baked = ed.bake() if self.removed else self.old_img
        for it in self.removed:
            ed.scene.removeItem(it)
        ed.set_base(transform_image(baked, self.op, self.arg))

    def undo(self):
        ed = self.ed
        if self.op == "crop":
            for it in self.shifted:
                it.setPos(it.pos() + QPointF(self.arg.x(), self.arg.y()))
            ed.set_base(self.old_img)
            return
        ed.set_base(self.old_img)
        for it in self.removed:
            ed.scene.addItem(it)


# ----------------------------------------------------------------------------- crop overlay
class CropOverlay(QGraphicsItem):
    HANDLES = ("tl", "t", "tr", "l", "r", "bl", "b", "br")
    CURSORS = {"tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor, "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
               "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor, "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
               "move": Qt.SizeAllCursor}

    def __init__(self, editor, bounds):
        super().__init__()
        self.ed = editor
        self.bounds = QRectF(bounds)
        self.r = QRectF(bounds)
        self.mode = None
        self.press = QPointF()
        self.r0 = QRectF()
        self.ratio = None
        self.guides = []
        self.setZValue(5000)
        self.setAcceptHoverEvents(True)

    def boundingRect(self):
        return self.bounds.adjusted(-30, -30, 30, 30)

    def _hs(self):
        return 10 / max(0.05, self.ed.view.scale_factor)

    def _hp(self, name):
        r = self.r
        x = r.left() if name.endswith("l") else r.right() if name.endswith("r") else r.center().x()
        y = r.top() if name.startswith("t") else r.bottom() if name.startswith("b") else r.center().y()
        return QPointF(x, y)

    def hit(self, pos):
        s = self._hs()
        for h in self.HANDLES:
            c = self._hp(h)
            if abs(pos.x() - c.x()) <= s and abs(pos.y() - c.y()) <= s:
                return h
        return "move" if self.r.contains(pos) else "new"

    def set_ratio(self, ratio):
        if ratio == "orig":
            ratio = self.bounds.width() / max(1, self.bounds.height())
        self.ratio = ratio
        if ratio:
            r = QRectF(self.r)
            w = r.width()
            h = w / ratio
            if h > self.bounds.height():
                h = self.bounds.height()
                w = h * ratio
            c = r.center()
            nr = QRectF(0, 0, w, h)
            nr.moveCenter(c)
            self.r = self._fit(nr)
            self.update()
            self.ed.crop_changed(self.r)

    def _fit(self, r):
        b = self.bounds
        r = QRectF(r)
        if r.width() > b.width():
            r.setWidth(b.width())
        if r.height() > b.height():
            r.setHeight(b.height())
        if r.left() < b.left():
            r.moveLeft(b.left())
        if r.top() < b.top():
            r.moveTop(b.top())
        if r.right() > b.right():
            r.moveRight(b.right())
        if r.bottom() > b.bottom():
            r.moveBottom(b.bottom())
        return r

    def paint(self, p, opt, widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        outer = QPainterPath()
        outer.addRect(self.bounds)
        inner = QPainterPath()
        inner.addRect(self.r)
        p.fillPath(outer.subtracted(inner), QColor(0, 0, 0, 150))
        pen = QPen(QColor("white"), 1.5)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(self.r)
        g = QPen(QColor(255, 255, 255, 80), 1)
        g.setCosmetic(True)
        p.setPen(g)
        for i in (1, 2):
            p.drawLine(QPointF(self.r.left() + self.r.width() * i / 3, self.r.top()),
                       QPointF(self.r.left() + self.r.width() * i / 3, self.r.bottom()))
            p.drawLine(QPointF(self.r.left(), self.r.top() + self.r.height() * i / 3),
                       QPointF(self.r.right(), self.r.top() + self.r.height() * i / 3))
        sn = QPen(QColor(255, 214, 10), 1.2, Qt.DashLine)     # snapping guides
        sn.setCosmetic(True)
        p.setPen(sn)
        for g in self.guides:
            if g[0] == "v":
                p.drawLine(QPointF(g[1], self.bounds.top()), QPointF(g[1], self.bounds.bottom()))
            else:
                p.drawLine(QPointF(self.bounds.left(), g[1]), QPointF(self.bounds.right(), g[1]))
        s = self._hs() / 2
        hp = QPen(QColor(10, 132, 255), 1.2)
        hp.setCosmetic(True)
        p.setPen(hp)
        p.setBrush(QColor("white"))
        for h in self.HANDLES:
            c = self._hp(h)
            p.drawRoundedRect(QRectF(c.x() - s, c.y() - s, 2 * s, 2 * s), s * 0.4, s * 0.4)

    def hoverMoveEvent(self, e):
        self.setCursor(self.CURSORS.get(self.hit(e.pos()), Qt.CrossCursor))

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        self.press = e.pos()
        self.mode = self.hit(e.pos())
        self.r0 = QRectF(self.r)
        if self.mode == "new":
            pt = self._clamp(e.pos())
            self.r = QRectF(pt, pt)
            self.r0 = QRectF(self.r)
        e.accept()

    def _clamp(self, pt):
        b = self.bounds
        return QPointF(min(max(pt.x(), b.left()), b.right()), min(max(pt.y(), b.top()), b.bottom()))

    def _snap(self, v, targets):
        tol = 7 / max(0.05, self.ed.view.scale_factor)
        for t in targets:
            if abs(v - t) <= tol:
                return t, True
        return v, False

    def mouseMoveEvent(self, e):
        if self.mode is None:
            return
        b, r0 = self.bounds, self.r0
        pos = self._clamp(e.pos())
        d = e.pos() - self.press
        self.guides = []
        xs = [b.left(), b.center().x(), b.right()]
        ys = [b.top(), b.center().y(), b.bottom()]
        if self.mode == "new":
            a = self._clamp(self.press)
            r = QRectF(a, pos).normalized()
            if self.ratio:
                w = r.width()
                h = w / self.ratio
                r = QRectF(a, QPointF(a.x() + (w if pos.x() >= a.x() else -w), a.y() + (h if pos.y() >= a.y() else -h))).normalized()
            self.r = self._fit(r)
        elif self.mode == "move":
            r = QRectF(r0)
            r.translate(d)
            cx, hx = self._snap(r.center().x(), xs)
            if hx:
                r.translate(cx - r.center().x(), 0)
                self.guides.append(("v", cx))
            else:
                for edge in (r.left(), r.right()):
                    v, ok = self._snap(edge, xs)
                    if ok:
                        r.translate(v - edge, 0)
                        self.guides.append(("v", v))
                        break
            cy, hy = self._snap(r.center().y(), ys)
            if hy:
                r.translate(0, cy - r.center().y())
                self.guides.append(("h", cy))
            else:
                for edge in (r.top(), r.bottom()):
                    v, ok = self._snap(edge, ys)
                    if ok:
                        r.translate(0, v - edge)
                        self.guides.append(("h", v))
                        break
            self.r = self._fit(r)
        else:
            l, t, rr, bb = r0.left(), r0.top(), r0.right(), r0.bottom()
            px_, hx = self._snap(pos.x(), xs)
            py_, hy = self._snap(pos.y(), ys)
            if hx:
                self.guides.append(("v", px_))
            if hy:
                self.guides.append(("h", py_))
            if "l" in self.mode:
                l = px_
            if "r" in self.mode:
                rr = px_
            if self.mode.startswith("t"):
                t = py_
            if self.mode.startswith("b"):
                bb = py_
            r = QRectF(QPointF(l, t), QPointF(rr, bb)).normalized()
            if self.ratio and r.width() > 1:
                if self.mode in ("l", "r"):
                    h = r.width() / self.ratio
                    r = QRectF(r.left(), r0.center().y() - h / 2, r.width(), h)
                elif self.mode in ("t", "b"):
                    w = r.height() * self.ratio
                    r = QRectF(r0.center().x() - w / 2, r.top(), w, r.height())
                else:
                    w = r.width()
                    h = w / self.ratio
                    ax = r0.right() if "l" in self.mode else r0.left()
                    ay = r0.bottom() if self.mode.startswith("t") else r0.top()
                    r = QRectF(QPointF(ax, ay), QPointF(ax + (w if "r" in self.mode else -w),
                                                         ay + (h if self.mode.startswith("b") else -h))).normalized()
                if not self.bounds.contains(r):
                    self.guides = []
                    return
            self.r = r
        self.prepareGeometryChange()
        self.update()
        self.ed.crop_changed(self.r)

    def mouseReleaseEvent(self, e):
        self.mode = None
        self.guides = []
        self.update()

    def mouseDoubleClickEvent(self, e):
        self.ed.apply_crop()

    def int_rect(self):
        return self.r.toAlignedRect().intersected(self.ed.base_image.rect())


# ----------------------------------------------------------------------------- canvas view
class AnnotView(QGraphicsView):
    zoomed = pyqtSignal(float)

    def __init__(self, editor):
        super().__init__(editor.scene)
        self.ed = editor
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setAcceptDrops(True)
        self.cur_item = None
        self.start = QPointF()
        self.press_states = {}
        self.scale_factor = 1.0
        self._pan = None
        self.set_canvas_color()

    def set_canvas_color(self):
        self.setBackgroundBrush(QBrush(Qt.NoBrush))

    # -- zoom / pan
    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
            self.scale(f, f)
            self.scale_factor *= f
            self.zoomed.emit(self.scale_factor)
        else:
            super().wheelEvent(e)

    def fit(self):
        self.resetTransform()
        r = self.scene().sceneRect()
        vp = self.viewport().size()
        f = min(1.0, (vp.width() - 60) / max(1, r.width()), (vp.height() - 60) / max(1, r.height()))
        self.scale(f, f)
        self.scale_factor = f
        self.centerOn(r.center())
        self.zoomed.emit(f)

    def actual_size(self):
        self.resetTransform()
        self.scale_factor = 1.0
        self.zoomed.emit(1.0)

    # -- drag & drop of images
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        e.acceptProposedAction()

    def dropEvent(self, e):
        self.ed.handle_drop(e.mimeData(), self.mapToScene(e.pos()))
        e.acceptProposedAction()

    # -- keys
    def keyPressEvent(self, e):
        ed = self.ed
        fi = self.scene().focusItem()
        if isinstance(fi, TextItem) and fi.textInteractionFlags() & Qt.TextEditorInteraction:
            if e.key() == Qt.Key_Escape:
                fi.clearFocus()
                return
            return super().keyPressEvent(e)
        if ed.crop_item is not None and e.key() in (Qt.Key_Return, Qt.Key_Enter):
            ed.apply_crop()
            return
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            ed.delete_selected()
            return
        if e.key() == Qt.Key_Escape:
            if ed.tool == "sticker":
                ed.cancel_sticker()
                return
            if ed.crop_item is not None:
                ed.cancel_crop_clicked()
                return
            self.scene().clearSelection()
            return
        if e.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down) and ed.tool == "select":
            step = 10 if e.modifiers() & Qt.ShiftModifier else 1
            d = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0), Qt.Key_Up: (0, -step), Qt.Key_Down: (0, step)}[e.key()]
            ed.nudge_selected(*d)
            return
        if not e.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
            t = ed.KEYS.get(e.text().lower())
            if t:
                ed.actions[t].setChecked(True)
                ed.set_tool(t)
                return
        super().keyPressEvent(e)

    # -- mouse
    def mousePressEvent(self, e):
        ed = self.ed
        tool = ed.tool
        if e.button() == Qt.MiddleButton:
            self._pan = e.pos()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if tool == "sticker":
            if e.button() == Qt.LeftButton:
                ed.place_sticker(self.mapToScene(e.pos()))
            elif e.button() == Qt.RightButton:
                ed.cancel_sticker()
            return
        if e.button() != Qt.LeftButton or tool in ("select", "crop"):
            if tool == "select" and e.button() == Qt.LeftButton:
                super().mousePressEvent(e)
                self.press_states = {i: i.to_dict() for i in self.scene().selectedItems() if is_ann(i)}
            else:
                super().mousePressEvent(e)
            return
        pos = self.mapToScene(e.pos())
        self.start = pos
        self.scene().clearSelection()
        c, w = ed.color, ed.width
        it = None
        if tool == "arrow":
            it = ArrowItem(pos, pos, c, w, ed.arrow_style)
        elif tool == "line":
            it = LineItem(pos.x(), pos.y(), pos.x(), pos.y())
            it.setPen(QPen(QColor(c), w, Qt.SolidLine, Qt.RoundCap))
        elif tool in ("rect", "ellipse"):
            it = RectItem(QRectF(pos, pos)) if tool == "rect" else EllipseItem(QRectF(pos, pos))
            it.setPen(QPen(QColor(c), w, Qt.SolidLine, Qt.SquareCap, Qt.RoundJoin))
            if tool == "rect" and ed.rounded:
                it.radius = 14
            if ed.fill:
                fc = QColor(c)
                fc.setAlpha(110)
                it.setBrush(fc)
        elif tool in ("pen", "highlighter"):
            it = PenItem(pos, c, w, highlighter=(tool == "highlighter"))
        elif tool in ("pixelate", "blur"):
            it = RedactItem(QRectF(pos, pos), "pixelate" if tool == "pixelate" else ed.redact_mode, ed)
        elif tool == "spotlight":
            it = SpotlightItem(QRectF(pos, pos), ed)
        elif tool == "counter":
            ed.add_item(CounterItem(pos, ed.next_counter(), c, w))
            return
        elif tool == "text":
            t = TextItem(pos, c, w, ed.remove_empty_text, ed.text_style, ed.text_family)
            ed.add_item(t)
            t.setFocus()
            return
        if it is not None:
            it.setFlag(QGraphicsItem.ItemIsSelectable, False)
            it.setZValue(0.5 if tool == "spotlight" else 1)
            self.cur_item = it
            self.scene().addItem(it)

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            d = e.pos() - self._pan
            self._pan = e.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - d.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - d.y())
            return
        pos = self.mapToScene(e.pos())
        self.ed.show_pos(pos)
        if self.ed.tool == "sticker":
            self.ed.move_ghost(pos)
            return
        it, tool = self.cur_item, self.ed.tool
        if it is not None and e.buttons() & Qt.LeftButton:
            shift = bool(e.modifiers() & Qt.ShiftModifier)
            if tool in ("arrow", "line"):
                end = pos
                if shift:
                    d = pos - self.start
                    a = round(math.atan2(d.y(), d.x()) / (math.pi / 4)) * (math.pi / 4)
                    L = math.hypot(d.x(), d.y())
                    end = self.start + QPointF(math.cos(a) * L, math.sin(a) * L)
                if tool == "arrow":
                    it.set_end(end)
                else:
                    it.setLine(self.start.x(), self.start.y(), end.x(), end.y())
            elif tool in ("rect", "ellipse", "pixelate", "blur", "spotlight"):
                r = QRectF(self.start, pos).normalized()
                if shift and tool in ("rect", "ellipse"):
                    m = max(r.width(), r.height())
                    r = QRectF(self.start, self.start + QPointF(m if pos.x() >= self.start.x() else -m,
                                                                m if pos.y() >= self.start.y() else -m)).normalized()
                it.prepareGeometryChange()
                it.setRect(r)
                if tool == "spotlight":
                    self.scene().update()
            elif tool in ("pen", "highlighter"):
                if shift:
                    it.points = [self.start, pos]
                    it.prepareGeometryChange()
                    from .items import smooth_path
                    it.setPath(smooth_path(it.points))
                else:
                    it.add_point(pos)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MiddleButton:
            self._pan = None
            self.setCursor(Qt.ArrowCursor if self.ed.tool == "select" else Qt.CrossCursor)
            return
        tool = self.ed.tool
        if self.cur_item is not None:
            it = self.cur_item
            self.cur_item = None
            self.scene().removeItem(it)
            bad = False
            if isinstance(it, (RectItem, EllipseItem, RedactItem, SpotlightItem)):
                bad = it.rect().width() < 4 and it.rect().height() < 4
            elif isinstance(it, LineItem):
                bad = it.line().length() < 3
            elif isinstance(it, ArrowItem):
                bad = (it.p2 - it.p1).manhattanLength() < 4
            if not bad:
                if isinstance(it, PenItem) and it.highlighter:
                    self.ed.smart_highlight(it)
                self.ed.add_item(it)
            return
        super().mouseReleaseEvent(e)
        if tool == "select" and self.press_states:
            for i, old in self.press_states.items():
                if i.scene():
                    self.ed.push_state(i, old, i.to_dict())
            self.press_states = {}


class DragButton(QPushButton):
    """'Drag me': drag the finished image straight into another app."""

    def __init__(self, editor):
        super().__init__("  끌어서 내보내기")
        self.ed = editor
        self.setToolTip("이미지를 다른 앱으로 끌어다 놓으세요 (바탕화면·탐색기·채팅창)")
        self.setCursor(Qt.OpenHandCursor)
        self._p = None

    def mousePressEvent(self, e):
        self._p = e.pos()

    def mouseMoveEvent(self, e):
        if self._p is None or (e.pos() - self._p).manhattanLength() < 8:
            return
        self._p = None
        img = self.ed.render_image()
        d = os.path.join(tempfile.gettempdir(), "BBongCapture")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "BBong Capture.png")
        img.save(path)
        mime = QMimeData()
        mime.setImageData(img)
        mime.setUrls([QUrl.fromLocalFile(path)])
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(QPixmap.fromImage(img.scaledToWidth(px(160), Qt.SmoothTransformation)))
        from .app import debug_log
        debug_log(f"drag start: {img.width()}x{img.height()} -> {path}")
        res = drag.exec_(Qt.CopyAction)
        debug_log(f"drag end: action={int(res)}")

    def mouseReleaseEvent(self, e):
        self._p = None


class ResizeDialog(QDialog):
    def __init__(self, w, h, parent=None):
        super().__init__(parent)
        self.setWindowTitle("이미지 크기 조정")
        self.ow, self.oh = w, h
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.w = QSpinBox()
        self.w.setRange(1, 20000)
        self.w.setValue(w)
        self.h = QSpinBox()
        self.h.setRange(1, 20000)
        self.h.setValue(h)
        self.pct = QSpinBox()
        self.pct.setRange(1, 800)
        self.pct.setValue(100)
        self.pct.setSuffix(" %")
        row.addWidget(QLabel("가로"))
        row.addWidget(self.w)
        row.addWidget(QLabel("세로"))
        row.addWidget(self.h)
        row.addWidget(self.pct)
        lay.addLayout(row)
        self.keep = QCheckBox("비율 유지")
        self.keep.setChecked(True)
        lay.addWidget(self.keep)
        bb = QHBoxLayout()
        bb.addStretch()
        ok = QPushButton("적용")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        no = QPushButton("취소")
        no.clicked.connect(self.reject)
        bb.addWidget(no)
        bb.addWidget(ok)
        lay.addLayout(bb)
        self._busy = False
        self.w.valueChanged.connect(lambda v: self._chg("w", v))
        self.h.valueChanged.connect(lambda v: self._chg("h", v))
        self.pct.valueChanged.connect(lambda v: self._chg("p", v))

    def _chg(self, src, v):
        if self._busy:
            return
        self._busy = True
        if src == "p":
            self.w.setValue(max(1, round(self.ow * v / 100)))
            self.h.setValue(max(1, round(self.oh * v / 100)))
        elif self.keep.isChecked():
            if src == "w":
                self.h.setValue(max(1, round(v * self.oh / self.ow)))
            else:
                self.w.setValue(max(1, round(v * self.ow / self.oh)))
            self.pct.setValue(max(1, round(self.w.value() * 100 / self.ow)))
        self._busy = False

    def size(self):
        return self.w.value(), self.h.value()


# ----------------------------------------------------------------------------- editor window
class EditorWindow(QMainWindow):
    pin_requested = pyqtSignal(object)
    saved = pyqtSignal(str)
    closed = pyqtSignal(object)

    TOOLS = [("select", "선택 / 이동", "V"), ("crop", "크롭", "C"), None,
             ("arrow", "화살표", "A"), ("line", "선", "L"), ("rect", "사각형", "R"), ("ellipse", "원", "O"),
             ("pen", "펜", "P"), ("highlighter", "형광펜", "H"), ("text", "텍스트", "T"), ("counter", "번호", "N"),
             None, ("spotlight", "스포트라이트", "S"), ("pixelate", "모자이크", "X"), ("blur", "블러", "B")]
    KEYS = {t[2].lower(): t[0] for t in TOOLS if t}

    def __init__(self, image: QImage, path=None, settings_=None):
        super().__init__()
        self.setWindowTitle("BBong Capture — 편집기")
        self.setAcceptDrops(False)
        self.path = path
        self.tool = "arrow"
        self._sticker_tab = 0
        self.color = PALETTE[0]
        self.width = 5
        self.fill = False
        self.rounded = False
        self.arrow_style = 0
        self.text_style = 0
        self.text_family = fonts.family()
        self.redact_mode = "blur"
        self.base_image = image.convertToFormat(QImage.Format_ARGB32)
        self.scene = QGraphicsScene(self)
        self.undo_stack = QUndoStack(self)
        self.bg_spec = BgSpec.from_dict(settings.data.get("bg_last")) if settings.data.get("bg_last") else BgSpec()
        self.bg_spec.kind = "none" if not settings.data.get("bg_last") else self.bg_spec.kind
        self._icons = []
        self._margins = None
        self._faded = False

        self.bg_item = BackgroundItem()
        self.bg_item.setZValue(Z_BG)
        self.scene.addItem(self.bg_item)
        self.base_item = BaseItem(QPixmap.fromImage(self.base_image))
        self.base_item.setZValue(Z_BASE)
        self.scene.addItem(self.base_item)
        self.shadow = QGraphicsDropShadowEffect()
        self.shadow.setEnabled(False)
        self.base_item.setGraphicsEffect(self.shadow)
        self.crop_item = None

        self.view = AnnotView(self)
        self.handles = HandlesItem(self)
        self.scene.addItem(self.handles)
        self.handles.setVisible(False)
        self.scene.selectionChanged.connect(self._sel_changed)

        self._build_ui()
        self.layout_background()
        scr = QApplication.primaryScreen().availableGeometry()
        self.resize(min(int(scr.width() * 0.9), max(px(980), self.base_image.width() + px(140))),
                    min(int(scr.height() * 0.9), max(px(640), self.base_image.height() + px(260))))
        self.actions["arrow"].setChecked(True)
        self.set_tool("arrow")

    # ------------------------------------------------------------------ UI construction
    def _tbtn(self, name, tip, slot=None, checkable=False, size=22):
        b = QToolButton()
        b.setIcon(icon(name))
        b.setIconSize(QSize(px(size), px(size)))
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setCursor(Qt.PointingHandCursor)
        if slot:
            b.clicked.connect(slot)
        self._icons.append((b, name))
        return b

    def _pill(self):
        f = QFrame()
        f.setObjectName("pill")
        lay = QHBoxLayout(f)
        lay.setContentsMargins(px(8), px(5), px(8), px(5))
        lay.setSpacing(px(2))
        return f, lay

    def _sep(self):
        s = QFrame()
        s.setFixedWidth(1)
        s.setStyleSheet(f"background:{C['border']};margin:{px(6)}px {px(4)}px;")
        return s

    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(px(14), px(12), px(14), px(10))
        root.setSpacing(px(10))
        self.setCentralWidget(central)

        # ---- top row: tools + actions
        top = QHBoxLayout()
        tools, tl = self._pill()
        self.actions = {}
        group = QActionGroup(self)
        self.tool_btns = {}
        for t in self.TOOLS:
            if t is None:
                tl.addWidget(self._sep())
                continue
            name, tip, key = t
            b = self._tbtn(name, f"{tip}  ({key})", checkable=True)
            b.clicked.connect(lambda _, n=name: self.set_tool(n))
            a = QAction(self)
            a.setCheckable(True)
            group.addAction(a)
            a.toggled.connect(b.setChecked)
            b.toggled.connect(lambda v, a=a: a.setChecked(v) if v else None)
            self.actions[name] = a
            self.tool_btns[name] = b
            tl.addWidget(b)
        top.addWidget(tools)
        top.addStretch()

        acts, al = self._pill()
        self.undo_btn = self._tbtn("undo", "실행 취소  (Ctrl+Z)", self.undo_stack.undo)
        self.redo_btn = self._tbtn("redo", "다시 실행  (Ctrl+Y)", self.undo_stack.redo)
        self.undo_stack.canUndoChanged.connect(self.undo_btn.setEnabled)
        self.redo_btn.setEnabled(False)
        self.undo_btn.setEnabled(False)
        self.undo_stack.canRedoChanged.connect(self.redo_btn.setEnabled)
        for b in (self.undo_btn, self.redo_btn):
            al.addWidget(b)
        al.addWidget(self._sep())
        for name, tip in (("rotl", "왼쪽으로 회전"), ("rotr", "오른쪽으로 회전"), ("fliph", "좌우 반전"), ("flipv", "상하 반전")):
            al.addWidget(self._tbtn(name, tip, lambda _, n=name: self.transform(n)))
        al.addWidget(self._tbtn("resize", "이미지 크기 조정", self.resize_dialog))
        al.addWidget(self._tbtn("image", "이미지 삽입 (여러 스크린샷 합치기)", self.insert_image_dialog))
        al.addWidget(self._sticker_button())
        al.addWidget(self._sep())
        al.addWidget(self._tbtn("pin", "화면에 고정  (Ctrl+P)", self.pin))
        al.addWidget(self._tbtn("copy", "클립보드에 복사  (Ctrl+C)", self.copy))
        al.addWidget(self._tbtn("save", "저장 (원본 파일에 덮어쓰기)  (Ctrl+S)", self.save))
        more = self._tbtn("more", "더보기")
        more.setPopupMode(QToolButton.InstantPopup)
        mm = round_menu(QMenu(self))
        mm.addAction("다른 이름으로 저장…  Ctrl+Shift+S", self.save_as)
        mm.addAction("프로젝트로 저장 (.bbcap)…", self.save_project_dialog)
        mm.addAction("프로젝트 열기…", self.open_project_dialog)
        mm.addSeparator()
        mm.addAction("클립보드 이미지 붙여넣기  Ctrl+V", self.paste)
        more.setMenu(mm)
        more.setStyleSheet("QToolButton::menu-indicator{image:none;}")
        al.addWidget(more)
        done = QPushButton("완료")
        done.setObjectName("primary")
        done.setToolTip("저장하고 클립보드에 복사한 뒤 닫기")
        done.clicked.connect(self.done)
        al.addSpacing(px(4))
        al.addWidget(done)
        top.addWidget(acts)
        root.addLayout(top)

        # ---- context row
        ctx, cl = self._pill()
        cl.setSpacing(px(6))
        self.colors_w = QWidget()
        self.color_lay = QHBoxLayout(self.colors_w)
        self.color_lay.setContentsMargins(0, 0, 0, 0)
        self.color_lay.setSpacing(px(5))
        cl.addWidget(self.colors_w)
        self.size_w = QWidget()
        sl = QHBoxLayout(self.size_w)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(self._sep())
        self.size_lbl_w = QLabel("굵기")
        sl.addWidget(self.size_lbl_w)
        self.size_s = QSlider(Qt.Horizontal)
        self.size_s.setRange(1, 24)
        self.size_s.setValue(self.width)
        self.size_s.setFixedWidth(px(110))
        self.size_s.valueChanged.connect(self._set_width)
        sl.addWidget(self.size_s)
        self.width_lbl = QLabel(str(self.width))
        self.width_lbl.setMinimumWidth(px(20))
        sl.addWidget(self.width_lbl)
        cl.addWidget(self.size_w)

        def combo(items, cur, slot):
            c = QComboBox()
            c.addItems(items)
            c.setCurrentIndex(cur)
            c.currentIndexChanged.connect(slot)
            return c

        self.arrow_w = QWidget()
        h = QHBoxLayout(self.arrow_w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self._sep())
        h.addWidget(QLabel("화살표"))
        self.arrow_cb = combo(ARROW_STYLES, 0, self._set_arrow_style)
        h.addWidget(self.arrow_cb)
        cl.addWidget(self.arrow_w)

        self.shape_w = QWidget()
        h = QHBoxLayout(self.shape_w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self._sep())
        self.fill_cb = QCheckBox("채우기")
        self.fill_cb.toggled.connect(self._set_fill)
        self.round_cb = QCheckBox("둥글게")
        self.round_cb.toggled.connect(self._set_rounded)
        h.addWidget(self.fill_cb)
        h.addWidget(self.round_cb)
        cl.addWidget(self.shape_w)

        self.text_w = QWidget()
        h = QHBoxLayout(self.text_w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self._sep())
        h.addWidget(QLabel("글자 스타일"))
        self.text_cb = combo(TEXT_STYLES, 0, self._set_text_style)
        h.addWidget(self.text_cb)
        h.addWidget(QLabel("폰트"))
        self.font_cb = QComboBox()
        self.font_cb.setMinimumWidth(px(150))
        for fam in fonts.text_families():
            self.font_cb.addItem(fam)
            self.font_cb.setItemData(self.font_cb.count() - 1, QFont(fam, 10), Qt.FontRole)
        self.font_cb.setCurrentText(self.text_family)
        self.font_cb.currentTextChanged.connect(self._set_text_family)
        h.addWidget(self.font_cb)
        cl.addWidget(self.text_w)

        self.redact_w = QWidget()
        h = QHBoxLayout(self.redact_w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel("블러 종류"))
        self.redact_cb = combo(["부드럽게", "보안 (복원 불가)"], 0, self._set_redact)
        h.addWidget(self.redact_cb)
        cl.addWidget(self.redact_w)

        self.crop_w = QWidget()
        h = QHBoxLayout(self.crop_w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel("비율"))
        self.ratio_cb = combo(list(CROP_RATIOS), 0, self._set_crop_ratio)
        h.addWidget(self.ratio_cb)
        self.crop_lbl = QLabel()
        self.crop_lbl.setObjectName("muted")
        h.addWidget(self.crop_lbl)
        ok = QPushButton("적용")
        ok.setObjectName("primary")
        ok.clicked.connect(self.apply_crop)
        no = QPushButton("취소")
        no.clicked.connect(self.cancel_crop_clicked)
        h.addWidget(ok)
        h.addWidget(no)
        cl.addWidget(self.crop_w)

        self.opacity_w = QWidget()
        h = QHBoxLayout(self.opacity_w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self._sep())
        h.addWidget(QLabel("크기"))
        self.isize_s = QSlider(Qt.Horizontal)
        self.isize_s.setRange(5, 150)
        self.isize_s.setValue(25)
        self.isize_s.setFixedWidth(px(150))
        self.isize_s.valueChanged.connect(self._set_img_size)
        self.isize_s.sliderPressed.connect(self._opacity_press)
        self.isize_s.sliderReleased.connect(self._opacity_release)
        h.addWidget(self.isize_s)
        self.isize_lbl = QLabel("25%")
        self.isize_lbl.setMinimumWidth(px(40))
        h.addWidget(self.isize_lbl)
        h.addWidget(self._sep())
        h.addWidget(QLabel("투명도"))
        self.opacity_s = QSlider(Qt.Horizontal)
        self.opacity_s.setRange(10, 100)
        self.opacity_s.setValue(100)
        self.opacity_s.setFixedWidth(px(130))
        self.opacity_s.valueChanged.connect(self._set_opacity)
        self.opacity_s.sliderPressed.connect(self._opacity_press)
        self.opacity_s.sliderReleased.connect(self._opacity_release)
        h.addWidget(self.opacity_s)
        self.opacity_lbl = QLabel("100%")
        self.opacity_lbl.setMinimumWidth(px(36))
        h.addWidget(self.opacity_lbl)
        cl.addWidget(self.opacity_w)

        self.hint_lbl = QLabel()
        self.hint_lbl.setObjectName("muted")
        cl.addWidget(self.hint_lbl)
        # option groups hug their content, so labels stay right next to their controls
        from PyQt5.QtWidgets import QSizePolicy
        for w in (self.colors_w, self.size_w, self.arrow_w, self.shape_w, self.text_w, self.redact_w, self.crop_w, self.opacity_w):
            w.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        cl.addStretch(1)
        root.addWidget(ctx)

        root.addWidget(self.view, 1)

        # ---- bottom row
        bot = QHBoxLayout()
        self.size_lbl = QLabel()
        self.size_lbl.setObjectName("muted")
        self.pos_lbl = QLabel()
        self.pos_lbl.setObjectName("muted")
        bot.addWidget(self.size_lbl)
        bot.addWidget(self.pos_lbl)
        bot.addStretch()
        self.drag_btn = DragButton(self)
        self.drag_btn.setIcon(icon("drag"))
        bot.addWidget(self.drag_btn)
        self.bg_btn = QPushButton("  배경")
        self.bg_btn.setIcon(icon("bg"))
        self.bg_btn.setCheckable(True)
        self.bg_btn.clicked.connect(self.show_bg_panel)
        bot.addWidget(self.bg_btn)
        self.theme_btn = self._tbtn("sun" if settings["theme"] == "dark" else "moon", "라이트 / 다크 모드", self.toggle_theme)
        bot.addWidget(self.theme_btn)
        self.zoom_lbl = QLabel("100%")
        self.zoom_lbl.setObjectName("muted")
        bot.addWidget(self.zoom_lbl)
        fit = QPushButton("맞춤")
        fit.clicked.connect(self.view.fit)
        one = QPushButton("100%")
        one.clicked.connect(self.view.actual_size)
        bot.addWidget(fit)
        bot.addWidget(one)
        root.addLayout(bot)
        self.view.zoomed.connect(lambda f: self.zoom_lbl.setText(f"{int(f * 100)}%"))

        # shortcuts
        for seq, slot in (("Ctrl+Z", self.undo_stack.undo), ("Ctrl+Shift+Z", self.undo_stack.redo),
                          ("Ctrl+Y", self.undo_stack.redo), ("Ctrl+S", self.save), ("Ctrl+Shift+S", self.save_as),
                          ("Ctrl+P", self.pin), ("Ctrl+C", self.copy), ("Ctrl+V", self.paste)):
            a = QAction(self)
            a.setShortcut(QKeySequence(seq))
            a.triggered.connect(slot)
            self.addAction(a)
        self._rebuild_colors()
        self._update_size_lbl()

    def refresh_icons(self):
        alive = []
        for b, name in self._icons:
            try:                       # colour-row buttons are rebuilt often; skip ones Qt already deleted
                b.setIcon(icon("sun" if (name in ("sun", "moon") and settings["theme"] == "dark") else
                               "moon" if name in ("sun", "moon") else name))
            except RuntimeError:
                continue
            alive.append((b, name))
        self._icons = alive
        self.drag_btn.setIcon(icon("drag"))
        self.bg_btn.setIcon(icon("bg"))
        self.view.set_canvas_color()
        self._rebuild_colors()

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_glassed", False):
            self._glassed = True
            glassify(self)
        self.view.fit()
        if not self._faded:
            self._faded = True
            self.setWindowOpacity(0.0)
            a = QPropertyAnimation(self, b"windowOpacity", self)
            a.setDuration(200)
            a.setStartValue(0.0)
            a.setEndValue(1.0)
            a.setEasingCurve(QEasingCurve.OutCubic)
            self._fade = a
            a.start()

    def closeEvent(self, e):
        self.closed.emit(self)
        super().closeEvent(e)

    # ------------------------------------------------------------------ colours
    def _swatch(self, c, fav=False):
        b = QPushButton()
        b.setFixedSize(px(22), px(22))
        sel = c.lower() == self.color.lower()
        b.setStyleSheet(f"QPushButton{{background:{c};border-radius:{px(11)}px;"
                        f"border:{3 if sel else 1}px solid {'#ffffff' if sel and C['mode'] == 'dark' else C['accent'] if sel else C['border']};padding:0;}}")
        b.setToolTip(c + ("  (우클릭: 즐겨찾기 삭제)" if fav else ""))
        b.clicked.connect(lambda _, c=c: self.set_color(c))
        if fav:
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda _, c=c: self._remove_fav(c))
        return b

    def _rebuild_colors(self):
        lay = self.color_lay
        while lay.count():
            w = lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        for c in PALETTE:
            lay.addWidget(self._swatch(c))
        favs = settings.data.get("fav_colors", [])
        if favs:
            lay.addWidget(self._sep())
            for c in favs[:10]:
                lay.addWidget(self._swatch(c, True))
        add = self._tbtn("plus", "현재 색을 즐겨찾기에 추가", self._add_fav, size=16)
        eye = self._tbtn("eyedrop", "화면에서 색 추출 (스포이드)", self.pick_color, size=18)
        more = self._tbtn("palette", "사용자 지정 색상 (색상 선택 창)", self._custom_color, size=19)
        lay.addWidget(self._sep())
        lay.addWidget(add)
        lay.addWidget(eye)
        lay.addWidget(more)

    def _custom_color(self):
        c = QColorDialog.getColor(QColor(self.color), self, "색상")
        if c.isValid():
            self.set_color(c.name())

    def _add_fav(self):
        favs = settings.data.setdefault("fav_colors", [])
        if self.color not in favs:
            favs.insert(0, self.color)
            del favs[10:]
            settings.save()
        self._rebuild_colors()

    def _remove_fav(self, c):
        favs = settings.data.get("fav_colors", [])
        if c in favs:
            favs.remove(c)
            settings.save()
        self._rebuild_colors()

    def pick_color(self):
        from .overlay import SelectionOverlay
        shot, origin = winutil.grab_virtual()
        ov = SelectionOverlay(shot, origin, "color", [])
        self._picker = ov
        ov.picked.connect(lambda c: (self.set_color(c.name()), self.toast(f"색상 추출  {c.name().upper()}")))
        ov.start()

    # ------------------------------------------------------------------ tool state
    def set_tool(self, name):
        self.tool = name
        if name != "sticker":
            self._drop_ghost()
        if name == "crop":
            self.start_crop()
        else:
            self.cancel_crop()
        select = name == "select"
        for it in self.annotation_items():
            it.setFlag(QGraphicsItem.ItemIsMovable, select)
            it.setFlag(QGraphicsItem.ItemIsSelectable, select)
            if isinstance(it, TextItem) and not select:
                it.setTextInteractionFlags(Qt.NoTextInteraction)
        if not select:
            self.scene.clearSelection()
        self.view.setCursor(Qt.ArrowCursor if select else Qt.CrossCursor)
        if name in self.tool_btns:
            self.tool_btns[name].setChecked(True)
        self.update_context()

    def update_context(self):
        t = self.tool
        show_color = t in ("select", "arrow", "line", "rect", "ellipse", "pen", "highlighter", "text", "counter")
        self.colors_w.setVisible(show_color)
        self.size_w.setVisible(show_color)
        sel = self._selected() if t == "select" else []
        one = sel[0] if len(sel) == 1 else None
        if t == "select":
            # in select mode only show the options that apply to the selected item
            show_color = one is not None and not isinstance(one, (RedactItem, SpotlightItem, ImageItem))
            self.colors_w.setVisible(show_color)
            self.size_w.setVisible(show_color)
            self.arrow_w.setVisible(isinstance(one, ArrowItem))
            self.shape_w.setVisible(isinstance(one, (RectItem, EllipseItem)))
            self.text_w.setVisible(isinstance(one, TextItem))
        else:
            self.arrow_w.setVisible(t == "arrow")
            self.shape_w.setVisible(t in ("rect", "ellipse"))
            self.text_w.setVisible(t == "text")
        self.size_lbl_w.setText("크기" if (t == "text" or isinstance(one, TextItem)) else "굵기")
        self.redact_w.setVisible(t == "blur")
        self.crop_w.setVisible(t == "crop")
        img = one if isinstance(one, ImageItem) else None
        self.opacity_w.setVisible(img is not None)
        if img is not None:
            v = int(round(img.opacity_ * 100))
            self.opacity_s.blockSignals(True)
            self.opacity_s.setValue(v)
            self.opacity_s.blockSignals(False)
            self.opacity_lbl.setText(f"{v}%")
            sv = int(round(img.rect().width() / max(1, self.base_image.width()) * 100))
            self.isize_s.blockSignals(True)
            self.isize_s.setValue(max(5, min(150, sv)))
            self.isize_s.blockSignals(False)
            self.isize_lbl.setText(f"{sv}%")
        hints = {"spotlight": "강조할 영역을 드래그하세요 — 나머지는 어두워집니다",
                 "pixelate": "가릴 영역을 드래그하세요 — 랜덤 노이즈가 적용된 모자이크",
                 "sticker": "붙일 곳을 클릭하세요 — 우클릭 · Esc 로 취소",
                 "select": "항목을 클릭해 선택 · 핸들로 크기 조절 · 방향키로 미세 이동 · Del 삭제"}
        self.hint_lbl.setText(hints.get(t, ""))
        self.hint_lbl.setVisible(t in hints)

    def set_color(self, c):
        self.color = c
        self._rebuild_colors()
        for it in self._selected():
            old = it.to_dict()
            it.set_color(QColor(c))
            self.push_state(it, old, it.to_dict())

    def _selected(self):
        return [i for i in self.scene.selectedItems() if is_ann(i)]

    def _set_width(self, v):
        self.width = v
        self.width_lbl.setText(str(v))
        for it in self._selected():
            old = it.to_dict()
            if isinstance(it, ArrowItem):
                it.w = v
                it.rebuild()
            elif isinstance(it, (LineItem, RectItem, EllipseItem)):
                p = it.pen()
                p.setWidthF(v)
                it.setPen(p)
            elif isinstance(it, PenItem):
                it.w = v
                it._style()
            elif isinstance(it, CounterItem):
                it.w = v
                it.r = 11 + v * 1.6
                it.setRect(-it.r, -it.r, 2 * it.r, 2 * it.r)
            elif isinstance(it, TextItem):
                it.w = v
                it.apply_style()
            self.push_state(it, old, it.to_dict())
            it.update()

    def _set_arrow_style(self, i):
        self.arrow_style = i
        for it in self._selected():
            if isinstance(it, ArrowItem):
                old = it.to_dict()
                it.style = i
                it.rebuild()
                self.push_state(it, old, it.to_dict())

    def _set_fill(self, v):
        self.fill = v
        for it in self._selected():
            if isinstance(it, (RectItem, EllipseItem)):
                old = it.to_dict()
                if v:
                    fc = QColor(it.pen().color())
                    fc.setAlpha(110)
                    it.setBrush(fc)
                else:
                    it.setBrush(QBrush(Qt.NoBrush))
                self.push_state(it, old, it.to_dict())

    def _set_rounded(self, v):
        self.rounded = v
        for it in self._selected():
            if isinstance(it, RectItem):
                old = it.to_dict()
                it.radius = 14 if v else 0
                self.push_state(it, old, it.to_dict())
                it.update()

    def _set_text_style(self, i):
        self.text_style = i
        for it in self._selected():
            if isinstance(it, TextItem):
                old = it.to_dict()
                it.style = i
                it.apply_style()
                self.push_state(it, old, it.to_dict())

    def _set_text_family(self, fam):
        self.text_family = fam
        for it in self._selected():
            if isinstance(it, TextItem):
                old = it.to_dict()
                it.family = fam
                it.apply_style()
                self.push_state(it, old, it.to_dict())

    def _set_redact(self, i):
        self.redact_mode = "blur" if i == 0 else "secure"

    def _sel_changed(self):
        sel = self._selected()
        if self.tool == "select":
            self.update_context()
        self.handles.set_target(sel[0] if len(sel) == 1 else None)
        if len(sel) == 1:                       # mirror the selected item's style in the option controls
            it = sel[0]
            if isinstance(it, ArrowItem):
                self.arrow_cb.blockSignals(True)
                self.arrow_cb.setCurrentIndex(it.style)
                self.arrow_cb.blockSignals(False)
            if isinstance(it, TextItem):
                self.text_cb.blockSignals(True)
                self.text_cb.setCurrentIndex(it.style)
                self.text_cb.blockSignals(False)
                self.font_cb.blockSignals(True)
                self.font_cb.setCurrentText(it.family)
                self.font_cb.blockSignals(False)

    def next_counter(self):
        nums = [i.number for i in self.scene.items() if isinstance(i, CounterItem)]
        return (max(nums) + 1) if nums else 1

    def show_pos(self, p):
        self.pos_lbl.setText(f"   x {int(p.x())}  y {int(p.y())}")

    def _update_size_lbl(self):
        self.size_lbl.setText(f"{self.base_image.width()} × {self.base_image.height()} px")

    def toast(self, text, ms=2500):
        lbl = getattr(self, "_toast", None)
        if lbl is None:
            lbl = self._toast = QLabel(self.view.viewport())
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(f"background:rgba(24,24,30,225);color:white;border:1px solid rgba(255,255,255,70);"
                              f"border-radius:{px(18)}px;padding:{px(10)}px {px(20)}px;font-weight:bold;")
            self._toast_timer = QTimer(self)
            self._toast_timer.setSingleShot(True)
            self._toast_timer.timeout.connect(lbl.hide)
        lbl.setText(text)
        lbl.adjustSize()
        lbl.move((self.view.viewport().width() - lbl.width()) // 2, px(16))
        lbl.show()
        lbl.raise_()
        self._toast_timer.start(ms)

    # ------------------------------------------------------------------ scene helpers
    def annotation_items(self):
        return [i for i in self.scene.items(Qt.AscendingOrder) if is_ann(i)]

    def add_item(self, item):
        sel = self.tool == "select"
        item.setFlag(QGraphicsItem.ItemIsMovable, sel)
        item.setFlag(QGraphicsItem.ItemIsSelectable, sel)
        if item.zValue() == 0:
            item.setZValue(1)
        self.undo_stack.push(AddCmd(self.scene, item))

    def push_state(self, item, old, new):
        if old != new:
            self.undo_stack.push(StateCmd(item, old, new))

    def remove_empty_text(self, item):
        if item.scene():
            self.scene.removeItem(item)

    def delete_selected(self):
        items = self._selected()
        if items:
            self.scene.clearSelection()
            self.undo_stack.push(RemoveCmd(self.scene, items))

    def nudge_selected(self, dx, dy):
        for it in self._selected():
            old = it.to_dict()
            it.setPos(it.pos() + QPointF(dx, dy))
            self.push_state(it, old, it.to_dict())

    def set_base(self, img):
        self.base_image = img
        self.base_item.setPixmap(QPixmap.fromImage(img))
        self._margins = None
        self.layout_background()
        self._update_size_lbl()
        self.scene.update()

    def after_geometry_change(self):
        self.view.fit()

    # ------------------------------------------------------------------ crop
    def start_crop(self):
        if self.crop_item is not None:
            return
        self.crop_item = CropOverlay(self, QRectF(self.base_image.rect()))
        self.scene.addItem(self.crop_item)
        self.ratio_cb.blockSignals(True)
        self.ratio_cb.setCurrentIndex(0)
        self.ratio_cb.blockSignals(False)
        self.crop_changed(self.crop_item.r)
        self.view.setCursor(Qt.CrossCursor)

    def cancel_crop(self):
        if self.crop_item is not None:
            self.scene.removeItem(self.crop_item)
            self.crop_item = None

    def crop_changed(self, r):
        self.crop_lbl.setText(f"{int(r.width())} × {int(r.height())}")

    def _set_crop_ratio(self, i):
        if self.crop_item is not None:
            self.crop_item.set_ratio(list(CROP_RATIOS.values())[i])

    def apply_crop(self):
        if self.crop_item is None:
            return
        r = self.crop_item.int_rect()
        self.cancel_crop()
        if r.width() > 4 and r.height() > 4 and r != self.base_image.rect():
            self.undo_stack.push(TransformCmd(self, "crop", r))
            self.after_geometry_change()
        self.tool_btns["select"].setChecked(True)
        self.set_tool("select")

    def cancel_crop_clicked(self):
        self.cancel_crop()
        self.tool_btns["select"].setChecked(True)
        self.set_tool("select")

    # ------------------------------------------------------------------ image operations
    def bake(self) -> QImage:
        """Base image + annotations flattened (no background)."""
        self.scene.clearSelection()
        old_rect = self.scene.sceneRect()
        vis = (self.bg_item.isVisible(), self.shadow.isEnabled(), self.handles.isVisible())
        self.bg_item.setVisible(False)
        self.shadow.setEnabled(False)
        self.handles.setVisible(False)
        rad = self.base_item.radius
        self.base_item.radius = 0
        r = QRectF(self.base_image.rect())
        img = QImage(self.base_image.size(), QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        self.scene.render(p, QRectF(img.rect()), r)
        p.end()
        self.base_item.radius = rad
        self.bg_item.setVisible(vis[0])
        self.shadow.setEnabled(vis[1])
        self.handles.setVisible(vis[2])
        return img.convertToFormat(QImage.Format_ARGB32)

    def transform(self, op, arg=None):
        self.cancel_crop()
        self.undo_stack.push(TransformCmd(self, op, arg))
        self.after_geometry_change()
        if self.tool == "crop":
            self.tool_btns["select"].setChecked(True)
            self.set_tool("select")

    def resize_dialog(self):
        d = ResizeDialog(self.base_image.width(), self.base_image.height(), self)
        if d.exec_() == QDialog.Accepted:
            w, h = d.size()
            if (w, h) != (self.base_image.width(), self.base_image.height()):
                self.transform("resize", (w, h))

    # ------------------------------------------------------------------ inserting images (combine screenshots)
    def insert_image(self, img: QImage, pos=None):
        if img.isNull():
            return
        maxw = self.base_image.width() * 0.6
        width = min(img.width(), maxw)
        h = width * img.height() / img.width()
        if pos is None:
            pos = QPointF((self.base_image.width() - width) / 2, (self.base_image.height() - h) / 2)
        else:
            pos = QPointF(pos.x() - width / 2, pos.y() - h / 2)
        it = ImageItem(img, pos, width)
        it.setZValue(0.7)
        self.tool_btns["select"].setChecked(True)
        self.set_tool("select")
        self.add_item(it)
        it.setSelected(True)
        self.toast("이미지를 추가했습니다 — 끌어서 위치를, 핸들로 크기를 조절하세요")

    def insert_image_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "이미지 삽입", "", "이미지 (*.png *.jpg *.jpeg *.bmp *.webp)")
        for p in paths:
            self.insert_image(QImage(p))

    # ------------------------------------------------------------------ stickers (짬뽕이 이모티콘)
    STICKER_SETS = (("짬뽕이", "bbong"), ("서리", "seori"))

    def _sticker_button(self):
        from PyQt5.QtWidgets import QButtonGroup, QGridLayout, QStackedWidget, QWidgetAction
        from .paths import res
        b = self._tbtn("sticker", "스티커 붙이기 (짬뽕이 · 서리)")
        b.setPopupMode(QToolButton.InstantPopup)
        menu = round_menu(QMenu(self))
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(px(8), px(8), px(8), px(8))
        v.setSpacing(px(8))
        tabs = QHBoxLayout()
        tabs.setSpacing(px(6))
        stack = QStackedWidget()
        group = QButtonGroup(box)
        group.setExclusive(True)
        for idx, (label, folder) in enumerate(self.STICKER_SETS):
            tb = QPushButton(label)
            tb.setCheckable(True)
            tb.setCursor(Qt.PointingHandCursor)
            tb.setMinimumHeight(px(28))
            tb.setStyleSheet(f"QPushButton{{border-radius:{px(14)}px;padding:0 {px(16)}px;font-weight:600;"
                             f"background:transparent;border:1px solid {C['border']};}}"
                             f"QPushButton:checked{{background:#0a84ff;color:white;border-color:#0a84ff;}}")
            group.addButton(tb, idx)
            tabs.addWidget(tb)
            page = QWidget()
            g = QGridLayout(page)
            g.setContentsMargins(0, 0, 0, 0)
            g.setSpacing(px(6))
            for i in range(9):
                img = QImage(res(f"stickers/{folder}/{i + 1:02d}.png"))
                if img.isNull():
                    continue
                sb = QToolButton()
                sb.setIcon(QIcon(QPixmap.fromImage(img)))
                sb.setIconSize(QSize(px(72), px(72)))
                sb.setAutoRaise(True)
                sb.setCursor(Qt.PointingHandCursor)
                sb.clicked.connect(lambda _, im=img, m=menu: (m.close(), self.start_sticker(im)))
                g.addWidget(sb, i // 3, i % 3)
            stack.addWidget(page)
        tabs.addStretch(1)
        group.buttonClicked[int].connect(lambda i: (stack.setCurrentIndex(i), setattr(self, "_sticker_tab", i)))
        first = getattr(self, "_sticker_tab", 0)
        group.button(first).setChecked(True)
        stack.setCurrentIndex(first)
        menu.aboutToShow.connect(lambda: (group.button(self._sticker_tab).setChecked(True),
                                          stack.setCurrentIndex(self._sticker_tab)))
        v.addLayout(tabs)
        v.addWidget(stack)
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(box)
        menu.addAction(wa)
        b.setMenu(menu)
        self.sticker_menu = menu
        return b

    def _sticker_width(self):
        return max(90.0, self.base_image.width() * 0.22)

    def start_sticker(self, img: QImage):
        """스티커를 고르면 반투명 미리보기가 포인터를 따라다니고, 클릭한 곳에 붙인다."""
        self._drop_ghost()
        self.sticker_img = img
        self.tool_btns["select"].setChecked(True)
        self.set_tool("sticker")
        w = self._sticker_width()
        h = w * img.height() / img.width()
        ghost = QGraphicsPixmapItem(QPixmap.fromImage(img).scaled(int(w), int(h), Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        ghost.setOpacity(0.55)
        ghost.setZValue(50)
        ghost.setAcceptedMouseButtons(Qt.NoButton)
        ghost.setVisible(False)
        self.scene.addItem(ghost)
        self.ghost = ghost
        self.view.setCursor(Qt.CrossCursor)
        vp = self.view.viewport()
        lp = vp.mapFromGlobal(QCursor.pos())
        if vp.rect().contains(lp):
            self.move_ghost(self.view.mapToScene(lp))

    def move_ghost(self, scene_pos):
        g = getattr(self, "ghost", None)
        if g is None:
            return
        r = g.boundingRect()
        g.setPos(scene_pos.x() - r.width() / 2, scene_pos.y() - r.height() / 2)
        g.setVisible(True)

    def _drop_ghost(self):
        g = getattr(self, "ghost", None)
        if g is not None:
            if g.scene() is not None:
                self.scene.removeItem(g)
            self.ghost = None

    def cancel_sticker(self):
        self.tool_btns["select"].setChecked(True)
        self.set_tool("select")

    def place_sticker(self, scene_pos):
        img = self.sticker_img
        if img is None:
            return
        width = self._sticker_width()
        h = width * img.height() / img.width()
        it = ImageItem(img, QPointF(scene_pos.x() - width / 2, scene_pos.y() - h / 2), width, sticker=True)
        it.setZValue(0.8)
        self.tool_btns["select"].setChecked(True)
        self.set_tool("select")
        self.add_item(it)
        it.setSelected(True)
        self.toast("붙였어요 — 위쪽 크기·투명도 슬라이더나 모서리 핸들로 조절하세요")

    def _set_img_size(self, v):
        self.isize_lbl.setText(f"{v}%")
        dragging = self.isize_s.isSliderDown()
        if not dragging:
            self._opacity_press()
        for it in self._opacity_targets():
            r = it.rect()
            c = it.mapToScene(r.center())
            w = max(10.0, self.base_image.width() * v / 100)
            h = w * it.image.height() / max(1, it.image.width())
            it.prepareGeometryChange()
            it.setRect(QRectF(0, 0, w, h))
            it.setPos(c.x() - w / 2, c.y() - h / 2)
            it.update()
        self.handles.set_target(self._selected()[0] if len(self._selected()) == 1 else None)
        if not dragging:
            self._opacity_release()

    def _opacity_targets(self):
        return [i for i in self._selected() if isinstance(i, ImageItem)]

    def _opacity_press(self):
        self._opacity_old = [(it, it.to_dict()) for it in self._opacity_targets()]

    def _set_opacity(self, v):
        self.opacity_lbl.setText(f"{v}%")
        dragging = self.opacity_s.isSliderDown()
        if not dragging:
            self._opacity_press()
        for it in self._opacity_targets():
            it.opacity_ = v / 100
            it.update()
        if not dragging:
            self._opacity_release()

    def _opacity_release(self):
        for it, old in getattr(self, "_opacity_old", []):
            self.push_state(it, old, it.to_dict())
        self._opacity_old = []

    def paste(self):
        fi = self.scene.focusItem()
        if isinstance(fi, TextItem) and fi.textInteractionFlags() & Qt.TextEditorInteraction:
            fi.textCursor().insertText(QApplication.clipboard().text())
            return
        self.handle_drop(QApplication.clipboard().mimeData(), None)

    def handle_drop(self, mime, scene_pos):
        n = 0
        if mime.hasUrls():
            for u in mime.urls():
                p = u.toLocalFile()
                if p.lower().endswith(".bbcap"):
                    continue
                img = QImage(p)
                if not img.isNull():
                    self.insert_image(img, scene_pos)
                    n += 1
        if n == 0 and mime.hasImage():
            img = QImage(mime.imageData())
            if not img.isNull():
                self.insert_image(img, scene_pos)

    # ------------------------------------------------------------------ background tool
    def show_bg_panel(self):
        panel = BackgroundPanel(self.bg_spec if self.bg_spec.active() else self._default_bg(), self)
        panel.changed.connect(self.set_bg)
        self._panel = panel
        panel.adjustSize()
        g = self.bg_btn.mapToGlobal(QPoint(self.bg_btn.width(), 0))
        panel.move(g.x() - panel.width(), g.y() - panel.height() - px(8))
        panel.show()
        self.bg_btn.setChecked(self.bg_spec.active())

    def _default_bg(self):
        s = BgSpec(kind="none")
        return s

    def set_bg(self, spec):
        self.bg_spec = spec
        self.bg_btn.setChecked(spec.active())
        settings.data["bg_last"] = spec.to_dict()
        self.layout_background()
        self.view.fit()

    def layout_background(self):
        spec = self.bg_spec
        w, h = self.base_image.width(), self.base_image.height()
        if spec.balance and spec.active() and self._margins is None:
            self._margins = imgutil.content_margins(self.base_image)
        canvas = layout(spec, w, h, self._margins if spec.balance else None)
        self.scene.setSceneRect(canvas)
        visual = spec.kind in ("gradient", "solid", "image", "wallpaper")
        self.bg_item.spec = spec
        self.bg_item.setRect(canvas)
        self.bg_item.setVisible(visual)
        self.base_item.radius = spec.radius if spec.active() else 0
        on = spec.active() and spec.shadow
        self.shadow.setEnabled(on)
        if on:
            self.shadow.setBlurRadius(spec.shadow_blur)
            self.shadow.setOffset(0, spec.shadow_blur / 4)
            self.shadow.setColor(QColor(0, 0, 0, int(255 * spec.shadow_opacity / 100)))
        self.base_item.update()
        self.bg_item.update()
        self.scene.update()

    # ------------------------------------------------------------------ smart highlighter
    def smart_highlight(self, item):
        """Snap a roughly horizontal highlighter stroke onto the detected text line."""
        pts = item.points
        if len(pts) < 2:
            return
        xs = [p.x() for p in pts]
        ys = [p.y() for p in pts]
        x0, x1 = int(min(xs)), int(max(xs))
        if x1 - x0 < 24 or (max(ys) - min(ys)) > max(24, (x1 - x0) * 0.35):
            return
        band = self._detect_text_band(x0, x1, int(sum(ys) / len(ys)))
        if band:
            top, bottom = band
            item.make_straight(thickness=(bottom - top) * 1.15, y=(top + bottom) / 2)
        else:
            item.make_straight()

    def _detect_text_band(self, x0, x1, y):
        img = self.base_image
        x0, x1 = max(0, x0), min(img.width() - 2, x1)
        top, bot = max(0, y - 60), min(img.height() - 1, y + 60)
        if x1 - x0 < 8 or bot - top < 10:
            return None
        g = imgutil.to_rgb(img.copy(x0, top, x1 - x0 + 1, bot - top + 1)).astype(np.int16).mean(axis=2)
        ink = np.abs(np.diff(g, axis=1)).mean(axis=1)
        if ink.max() < 3:
            return None
        ink = np.convolve(ink, np.ones(3) / 3, mode="same")
        thr = ink.max() * 0.35
        yy = min(max(y - top, 0), len(ink) - 1)
        rows = np.where(ink > thr)[0]
        if rows.size == 0:
            return None
        near = rows[np.argmin(np.abs(rows - yy))]
        a = b = near
        gap = 0
        while a > 0 and (ink[a - 1] > thr or gap < 2):
            gap = 0 if ink[a - 1] > thr else gap + 1
            a -= 1
            if gap >= 2:
                a += gap
                break
        gap = 0
        while b < len(ink) - 1 and (ink[b + 1] > thr or gap < 2):
            gap = 0 if ink[b + 1] > thr else gap + 1
            b += 1
            if gap >= 2:
                b -= gap
                break
        h = b - a + 1
        if h < 7 or h > 90:
            return None
        return top + a - 2, top + b + 2

    # ------------------------------------------------------------------ theme
    def toggle_theme(self):
        mode = "light" if settings["theme"] == "dark" else "dark"
        settings["theme"] = mode
        settings.save()
        apply_theme(QApplication.instance(), mode)
        self.refresh_icons()

    # ------------------------------------------------------------------ output
    def render_image(self) -> QImage:
        self.scene.clearSelection()
        fi = self.scene.focusItem()
        if fi:
            fi.clearFocus()
        crop_vis = self.crop_item.isVisible() if self.crop_item else None
        if self.crop_item:
            self.crop_item.setVisible(False)
        self.handles.setVisible(False)
        rect = self.scene.sceneRect()
        img = QImage(int(round(rect.width())), int(round(rect.height())), QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        self.scene.render(p, QRectF(img.rect()), rect)
        p.end()
        if self.crop_item:
            self.crop_item.setVisible(crop_vis)
        return img

    def copy(self):
        fi = self.scene.focusItem()
        if isinstance(fi, TextItem) and fi.textCursor().hasSelection():
            QApplication.clipboard().setText(fi.textCursor().selectedText())
            return
        QApplication.clipboard().setImage(self.render_image())
        self.toast("클립보드에 복사했습니다")

    def _write(self, path):
        if path.lower().endswith(".bbcap"):
            ok = self.save_project(path)
        else:
            img = self.render_image()
            ext = os.path.splitext(path)[1].lower()
            if ext in (".jpg", ".jpeg"):
                bg = QImage(img.size(), QImage.Format_RGB32)
                bg.fill(Qt.white)
                p = QPainter(bg)
                p.drawImage(0, 0, img)
                p.end()
                img = bg
            ok = img.save(path, None, 95 if ext in (".jpg", ".jpeg") else -1)
        if ok:
            self.saved.emit(path)
        return ok

    def save(self):
        if not self.path or self._in_temp(self.path):
            return self.save_as()
        if self._write(self.path):
            self.toast(f"저장했습니다\n{self.path}")
            return True
        return False

    @staticmethod
    def _in_temp(path):
        try:
            return os.path.normcase(os.path.dirname(os.path.abspath(path))) == os.path.normcase(str(settings.temp_dir()))
        except Exception:
            return False

    def save_as(self):
        start = self.path if (self.path and not self._in_temp(self.path)) else str(settings.save_dir() / "BBongCapture.png")
        path, _ = QFileDialog.getSaveFileName(self, "다른 이름으로 저장", start,
                                              "PNG (*.png);;JPEG (*.jpg);;BMP (*.bmp);;BBong Capture 프로젝트 (*.bbcap)")
        if path and self._write(path):
            self.path = path
            self.toast(f"저장했습니다\n{path}")
            return True
        return False

    def pin(self):
        self.pin_requested.emit(self.render_image())

    def done(self):
        if self.path and not self.path.lower().endswith(".bbcap"):
            self._write(self.path)
        QApplication.clipboard().setImage(self.render_image())
        self.close()

    # ------------------------------------------------------------------ project files
    def project_dict(self):
        from . import imgutil as iu
        self.cancel_crop()
        return {"version": 1, "base": iu.to_b64(self.base_image), "bg": self.bg_spec.to_dict(),
                "items": [it.to_dict() for it in self.annotation_items()]}

    def save_project(self, path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.project_dict(), f)
            return True
        except Exception:
            return False

    def save_project_dialog(self):
        start = os.path.splitext(self.path)[0] + ".bbcap" if self.path else "screenshot.bbcap"
        path, _ = QFileDialog.getSaveFileName(self, "프로젝트로 저장", start, "BBong Capture 프로젝트 (*.bbcap)")
        if path and self.save_project(path):
            self.toast(f"프로젝트를 저장했습니다\n{path}")

    def open_project_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "프로젝트 열기", "", "BBong Capture 프로젝트 (*.bbcap)")
        if path:
            self.load_project(path)

    def load_project(self, path):
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        for it in self.annotation_items():
            self.scene.removeItem(it)
        self.undo_stack.clear()
        self.bg_spec = BgSpec.from_dict(d.get("bg"))
        self.base_image = imgutil.from_b64(d["base"]).convertToFormat(QImage.Format_ARGB32)
        self.base_item.setPixmap(QPixmap.fromImage(self.base_image))
        self._margins = None
        for itd in d.get("items", []):
            try:
                it = item_from_dict(itd, self)
            except Exception:
                continue
            if it.zValue() == 0:
                it.setZValue(1)
            self.scene.addItem(it)
        self.layout_background()
        self._update_size_lbl()
        self.bg_btn.setChecked(self.bg_spec.active())
        self.set_tool(self.tool)
        self.view.fit()
        self.path = path

    @staticmethod
    def open_project(path):
        ed = EditorWindow(QImage(8, 8, QImage.Format_ARGB32))
        ed.load_project(path)
        return ed
