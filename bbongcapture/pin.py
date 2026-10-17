"""Floating (pinned) screenshots: always on top, resizable, adjustable opacity, lock mode."""
import cv2
import numpy as np
from PyQt5.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import QApplication, QFileDialog, QMenu, QWidget

from . import imgutil
from .theme import icon, px, round_menu

PAD = 14


def _shadow(w, h, radius):
    p = px(PAD)
    img = QImage(w, h, QImage.Format_Grayscale8)
    img.fill(0)
    qp = QPainter(img)
    qp.setRenderHint(QPainter.Antialiasing)
    qp.setPen(Qt.NoPen)
    qp.setBrush(QColor(255, 255, 255))
    qp.drawRoundedRect(QRectF(p, p + px(4), w - 2 * p, h - 2 * p), radius, radius)
    qp.end()
    arr = np.frombuffer(img.constBits().asstring(img.bytesPerLine() * h), np.uint8).reshape(h, img.bytesPerLine())[:, :w]
    arr = cv2.GaussianBlur(arr.copy(), (0, 0), px(6))
    out = np.zeros((h, w, 4), np.uint8)
    out[..., 3] = (arr.astype(np.float32) * 0.5).astype(np.uint8)
    return QPixmap.fromImage(imgutil.from_rgba_premul(out))


class PinWindow(QWidget):
    closed = pyqtSignal(object)
    edit_requested = pyqtSignal(object)

    def __init__(self, image: QImage, at=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.image = image
        self.scale_f = 1.0
        self.opac = 1.0
        self.locked = False
        self.drag = None
        self.radius = px(10)
        self.setFocusPolicy(Qt.StrongFocus)
        self._apply_size(initial=True)
        if at:
            self.move(at)
        self.setToolTip("드래그: 이동 · 방향키: 위치 미세 조정 (Shift: 10px) · 휠: 크기 · Ctrl+휠: 투명도 · 더블클릭 / Esc: 닫기 · 우클릭: 메뉴")

    # ------------------------------------------------------------------ geometry
    def _apply_size(self, initial=False):
        p = px(PAD)
        w, h = int(self.image.width() * self.scale_f), int(self.image.height() * self.scale_f)
        w, h = max(60, w), max(40, h)
        c = self.geometry().center() if self.isVisible() else None
        self.setFixedSize(w + 2 * p, h + 2 * p)
        self._shadow = _shadow(self.width(), self.height(), self.radius)
        if c is not None:
            r = self.geometry()
            r.moveCenter(c)
            self.move(r.topLeft())

    def card_rect(self):
        p = px(PAD)
        return QRectF(p, p, self.width() - 2 * p, self.height() - 2 * p)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.SmoothPixmapTransform | QPainter.Antialiasing)
        p.setOpacity(self.opac)
        p.drawPixmap(0, 0, self._shadow)
        r = self.card_rect()
        path = QPainterPath()
        path.addRoundedRect(r, self.radius, self.radius)
        p.save()
        p.setClipPath(path)
        p.drawImage(r, self.image)
        p.restore()
        focus = self.hasFocus() and not self.locked
        p.setPen(QPen(QColor(10, 132, 255, 230) if focus else QColor(255, 255, 255, 70), 2 if focus else 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        if self.locked:
            p.setOpacity(0.9)
            ic = icon("lock", "#ffffff").pixmap(px(18), px(18))
            p.setBrush(QColor(0, 0, 0, 140))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(r.right() - px(30), r.top() + px(8), px(24), px(24)), px(12), px(12))
            p.drawPixmap(int(r.right() - px(27)), int(r.top() + px(11)), ic)

    # ------------------------------------------------------------------ show / close with fades
    def show(self):
        self.setWindowOpacity(0.0)
        super().show()
        a = QPropertyAnimation(self, b"windowOpacity", self)
        a.setDuration(200)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setEasingCurve(QEasingCurve.OutCubic)
        self._in = a
        a.start()

    def close_animated(self):
        if getattr(self, "_closing", False):
            return
        self._closing = True
        a = QPropertyAnimation(self, b"windowOpacity", self)
        a.setDuration(160)
        a.setStartValue(self.windowOpacity())
        a.setEndValue(0.0)
        a.finished.connect(self.close)
        self._out = a
        a.start()

    # ------------------------------------------------------------------ input
    def wheelEvent(self, e):
        d = e.angleDelta().y()
        if e.modifiers() & Qt.ControlModifier:
            self.opac = min(1.0, max(0.1, self.opac + (0.05 if d > 0 else -0.05)))
        else:
            self.scale_f = min(8.0, max(0.1, self.scale_f * (1.1 if d > 0 else 1 / 1.1)))
            self._apply_size()
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.drag = e.globalPos() - self.frameGeometry().topLeft()
            self.setFocus()
            self.update()

    def mouseMoveEvent(self, e):
        if self.drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() - self.drag)

    def mouseReleaseEvent(self, e):
        self.drag = None

    def mouseDoubleClickEvent(self, e):
        self.close_animated()

    def focusOutEvent(self, e):
        self.update()
        super().focusOutEvent(e)

    def keyPressEvent(self, e):
        step = 10 if e.modifiers() & Qt.ShiftModifier else 1
        k = e.key()
        if k == Qt.Key_Escape:
            self.close_animated()
        elif k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            d = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0), Qt.Key_Up: (0, -step), Qt.Key_Down: (0, step)}[k]
            self.move(self.pos() + QPoint(*d))
        elif k == Qt.Key_C and e.modifiers() & Qt.ControlModifier:
            QApplication.clipboard().setImage(self.image)
        elif k in (Qt.Key_Plus, Qt.Key_Equal):
            self.scale_f = min(8.0, self.scale_f * 1.1)
            self._apply_size()
            self.update()
        elif k == Qt.Key_Minus:
            self.scale_f = max(0.1, self.scale_f / 1.1)
            self._apply_size()
            self.update()

    # ------------------------------------------------------------------ lock mode (click-through)
    def set_locked(self, on):
        if on == self.locked:
            return
        self.locked = on
        self.setWindowFlag(Qt.WindowTransparentForInput, on)
        self.show_no_anim()
        self.update()

    def show_no_anim(self):
        super().show()
        self.setWindowOpacity(1.0)

    def contextMenuEvent(self, e):
        m = round_menu(QMenu(self))
        m.addAction(icon("copy"), "복사", lambda: QApplication.clipboard().setImage(self.image))
        m.addAction(icon("save"), "다른 이름으로 저장…", self._save)
        m.addAction(icon("edit"), "편집", lambda: self.edit_requested.emit(self.image))
        m.addSeparator()
        sz = m.addMenu("크기")
        for label, f in (("50%", 0.5), ("100% (원본)", 1.0), ("150%", 1.5), ("200%", 2.0)):
            sz.addAction(label, lambda f=f: (setattr(self, "scale_f", f), self._apply_size(), self.update()))
        o = m.addMenu("투명도")
        for v in (100, 80, 60, 40, 20):
            o.addAction(f"{v}%", lambda v=v: (setattr(self, "opac", v / 100), self.update()))
        m.addAction(icon("lock"), "잠금 모드 (클릭 통과) — Ctrl+Shift+L 로 해제", lambda: self.set_locked(True))
        m.addSeparator()
        m.addAction(icon("close"), "닫기", self.close_animated)
        m.exec_(e.globalPos())

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, "고정한 이미지 저장", "pinned.png", "PNG (*.png);;JPEG (*.jpg)")
        if path:
            self.image.save(path)

    def closeEvent(self, e):
        self.closed.emit(self)
        super().closeEvent(e)
