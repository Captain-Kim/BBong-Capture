"""Quick Access overlay: rounded, animated thumbnail cards shown after each capture."""
import os

import cv2
import numpy as np
from PyQt5.QtCore import (QEasingCurve, QMimeData, QParallelAnimationGroup, QPoint, QPropertyAnimation, QRectF, QSize,
                          Qt, QUrl, QVariantAnimation, pyqtSignal)
from PyQt5.QtGui import QColor, QDrag, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import QGraphicsOpacityEffect, QMenu, QPushButton, QWidget

from . import imgutil, winutil
from .theme import icon, px, round_menu

SIZES = {"small": (190, 120), "medium": (250, 158), "large": (320, 202)}
PAD = 16  # room around the card for its shadow


def _shadow_pixmap(w, h, radius):
    m = np.zeros((h, w), np.uint8)
    p = px(PAD)
    img = QImage(w, h, QImage.Format_Grayscale8)
    img.fill(0)
    qp = QPainter(img)
    qp.setRenderHint(QPainter.Antialiasing)
    qp.setPen(Qt.NoPen)
    qp.setBrush(QColor(255, 255, 255))
    qp.drawRoundedRect(QRectF(p, p + px(5), w - 2 * p, h - 2 * p), radius, radius)
    qp.end()
    arr = np.frombuffer(img.constBits().asstring(img.bytesPerLine() * h), np.uint8).reshape(h, img.bytesPerLine())[:, :w]
    arr = cv2.GaussianBlur(arr.copy(), (0, 0), px(7))
    out = np.zeros((h, w, 4), np.uint8)
    out[..., 3] = (arr.astype(np.float32) * 0.55).astype(np.uint8)
    return QPixmap.fromImage(imgutil.from_rgba_premul(out))


from .fonts import family as _fam  # noqa: E402


class GlassButton(QPushButton):
    def __init__(self, text, parent, ic=None, round_=False):
        super().__init__(text, parent)
        if ic:
            self.setIcon(icon(ic, "#ffffff"))
            self.setIconSize(QSize(px(15), px(15)))
        r = px(15)
        self.setFixedHeight(px(30))
        if round_:
            self.setFixedWidth(px(30))
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"QPushButton{{background:rgba(24,24,28,205);color:white;border:1px solid rgba(255,255,255,40);"
                           f"border-radius:{r}px;padding:0 {px(10)}px;font-weight:600;}}"
                           f"QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #4aa3ff,stop:1 #0a84ff);border-color:#0a84ff;}}"
                           f"QPushButton:pressed{{background:#0868cc;}}")
        self.eff = QGraphicsOpacityEffect(self)
        self.eff.setOpacity(0.0)
        self.setGraphicsEffect(self.eff)
        self.hide()


class QuickAccessCard(QWidget):
    closed = pyqtSignal(object)
    action = pyqtSignal(str, object)  # name, card

    def __init__(self, thumb: QImage, path: str, kind="image", seconds=7, size="medium", edge=-1, info=True):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.path, self.kind, self.thumb = path, kind, thumb
        self.seconds, self.edge, self.show_info = seconds, edge, info
        cw, ch = SIZES.get(size, SIZES["medium"])
        self.cw, self.ch = px(cw), px(ch)
        self.radius = px(18)
        self.setFixedSize(self.cw + 2 * px(PAD), self.ch + 2 * px(PAD))
        self.shadow = _shadow_pixmap(self.width(), self.height(), self.radius)
        self.hover_t = 0.0
        self.progress = 0.0
        self.press = None
        self.mode = None
        self.dismissing = False
        self.anim_group = None
        self._pos_anim = None

        self.hover_anim = QVariantAnimation(self)
        self.hover_anim.setDuration(150)
        self.hover_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.hover_anim.valueChanged.connect(self._hover_changed)

        self.timer_anim = QVariantAnimation(self)
        self.timer_anim.setStartValue(0.0)
        self.timer_anim.setEndValue(1.0)
        self.timer_anim.setDuration(int(max(1, seconds) * 1000))
        self.timer_anim.valueChanged.connect(self._timer_changed)
        self.timer_anim.finished.connect(lambda: self.dismiss())

        self.btns = []
        self._build_buttons()
        self.setWindowOpacity(0.0)

    # ------------------------------------------------------------------ build
    def _geom(self):
        p = px(PAD)
        return QRectF(p, p, self.cw, self.ch)

    def _build_buttons(self):
        g = self._geom()
        x0, y0 = int(g.left()), int(g.top())
        cx = x0 + self.cw // 2
        cy = y0 + self.ch // 2
        bw = px(88)
        gap = px(8)

        def mk(text, name, ic, x, y, w=None, round_=False):
            b = GlassButton(text, self, ic, round_)
            if w:
                b.setFixedWidth(w)
            b.move(int(x), int(y))
            b.clicked.connect(lambda: self.action.emit(name, self))
            self.btns.append(b)
            return b

        row1 = cy - px(34)
        row2 = cy + px(4)
        if self.kind == "image":
            mk("복사", "copy", "copy", cx - bw - gap // 2, row1, bw)
            mk("저장", "save_as", "save", cx + gap // 2, row1, bw)
            mk("편집", "edit", "edit", cx - bw - gap // 2, row2, bw)
            mk("고정", "pin", "pin", cx + gap // 2, row2, bw)
        else:
            mk("복사", "copy", "copy", cx - bw - gap // 2, row1, bw)
            mk("열기", "open", "open", cx + gap // 2, row1, bw)
            mk("폴더", "folder", "folder", cx - bw - gap // 2, row2, bw)
            mk("삭제", "delete", "trash", cx + gap // 2, row2, bw)
        mk("", "close", "close", x0 + px(10), y0 + px(10), round_=True)
        more = mk("", "more", "more", x0 + self.cw - px(40), y0 + px(10), round_=True)
        more.clicked.disconnect()
        more.clicked.connect(self._more_menu)

    def _more_menu(self):
        m = round_menu(QMenu(self))
        m.addAction(icon("folder"), "폴더에서 보기", lambda: self.action.emit("folder", self))
        if self.kind == "image":
            m.addAction(icon("copy"), "파일 경로 복사", lambda: self.action.emit("copy_path", self))
        m.addAction(icon("trash"), "휴지통으로 이동", lambda: self.action.emit("delete", self))
        m.addSeparator()
        m.addAction(icon("close"), "닫기", lambda: self.action.emit("close", self))
        m.exec_(self.mapToGlobal(QPoint(self.width() - px(PAD) - px(40), px(PAD) + px(44))))

    # ------------------------------------------------------------------ animation
    def _hover_changed(self, v):
        self.hover_t = float(v)
        for b in self.btns:
            b.eff.setOpacity(self.hover_t)
            b.setVisible(self.hover_t > 0.02)
        self.update()

    def _timer_changed(self, v):
        self.progress = float(v)
        self.update()

    def _fade_hover(self, to):
        self.hover_anim.stop()
        self.hover_anim.setStartValue(self.hover_t)
        self.hover_anim.setEndValue(to)
        self.hover_anim.start()

    def enterEvent(self, e):
        self._fade_hover(1.0)
        if self.timer_anim.state() == QVariantAnimation.Running:
            self.timer_anim.pause()

    def leaveEvent(self, e):
        if self.mode is None:
            self._fade_hover(0.0)
            if self.seconds > 0 and not self.dismissing and self.timer_anim.state() == QVariantAnimation.Paused:
                self.timer_anim.resume()

    def animate_to(self, target: QPoint, ms=260, curve=QEasingCurve.OutCubic):
        if self._pos_anim is not None:
            self._pos_anim.stop()
        a = QPropertyAnimation(self, b"pos", self)
        a.setDuration(ms)
        a.setEasingCurve(curve)
        a.setEndValue(target)
        self._pos_anim = a
        a.start()

    def slide_in(self, target: QPoint):
        """Fade + slide in from the screen edge."""
        start = QPoint(target.x() + self.edge * px(46), target.y())
        self.move(start)
        super().show()
        winutil.exclude_from_capture(self)
        g = QParallelAnimationGroup(self)
        a = QPropertyAnimation(self, b"pos")
        a.setDuration(340)
        a.setStartValue(start)
        a.setEndValue(target)
        a.setEasingCurve(QEasingCurve.OutBack)
        a.setEasingCurve(QEasingCurve(QEasingCurve.OutCubic))
        o = QPropertyAnimation(self, b"windowOpacity")
        o.setDuration(260)
        o.setStartValue(0.0)
        o.setEndValue(1.0)
        o.setEasingCurve(QEasingCurve.OutCubic)
        g.addAnimation(a)
        g.addAnimation(o)
        self.anim_group = g
        g.finished.connect(self._start_timer)
        g.start()

    def _start_timer(self):
        self.progress = 0.0
        if self.seconds > 0 and not self.underMouse():
            self.timer_anim.start()

    def dismiss(self, swipe_dir=None):
        """Slide out + fade, then close."""
        if self.dismissing:
            return
        self.dismissing = True
        self.timer_anim.stop()
        d = swipe_dir if swipe_dir is not None else self.edge
        g = QParallelAnimationGroup(self)
        a = QPropertyAnimation(self, b"pos")
        a.setDuration(240)
        a.setEndValue(QPoint(self.x() + d * px(70), self.y()))
        a.setEasingCurve(QEasingCurve.InCubic)
        o = QPropertyAnimation(self, b"windowOpacity")
        o.setDuration(220)
        o.setStartValue(self.windowOpacity())
        o.setEndValue(0.0)
        o.setEasingCurve(QEasingCurve.InCubic)
        g.addAnimation(a)
        g.addAnimation(o)
        self.anim_group = g
        g.finished.connect(self._finish_close)
        g.start()

    def close_card(self):
        self.dismiss()

    def close_now(self):
        self.timer_anim.stop()
        self._finish_close()

    def _finish_close(self):
        self.hide()
        self.closed.emit(self)
        self.deleteLater()

    # ------------------------------------------------------------------ painting
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        p.drawPixmap(0, 0, self.shadow)
        g = self._geom()
        path = QPainterPath()
        path.addRoundedRect(g, self.radius, self.radius)
        p.fillPath(path, QColor(28, 28, 32))
        p.setClipPath(path)
        if not self.thumb.isNull():
            t = self.thumb.scaled(g.size().toSize(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p.drawImage(int(g.left() + (g.width() - t.width()) / 2), int(g.top() + (g.height() - t.height()) / 2), t)
        if self.hover_t > 0:
            p.fillRect(g, QColor(0, 0, 0, int(135 * self.hover_t)))
        if self.kind != "image" and self.hover_t < 0.5:
            c = g.center()
            p.setBrush(QColor(0, 0, 0, int(150 * (1 - self.hover_t))))
            p.setPen(Qt.NoPen)
            p.drawEllipse(c, px(19), px(19))
            p.setBrush(QColor(255, 255, 255, int(255 * (1 - self.hover_t))))
            p.drawPolygon(*[c + QPoint(dx, dy) for dx, dy in ((-px(5), -px(8)), (-px(5), px(8)), (px(9), 0))])
        # file info footer
        if self.show_info and self.hover_t > 0:
            f = QFont(_fam(), 8)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(255, 255, 255, int(235 * self.hover_t)))
            p.drawText(QRectF(g.left() + px(14), g.bottom() - px(30), g.width() - px(28), px(22)),
                       Qt.AlignLeft | Qt.AlignVCenter, self._info_text())
        # auto-close progress bar
        if self.seconds > 0 and self.progress > 0 and not self.dismissing:
            w = g.width() * (1 - self.progress)
            p.fillRect(QRectF(g.left(), g.bottom() - px(3), w, px(3)), QColor(10, 132, 255, 200))
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 50), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

    def _info_text(self):
        try:
            size = os.path.getsize(self.path)
        except OSError:
            size = 0
        kb = size / 1024
        s = f"{kb / 1024:.1f} MB" if kb > 1024 else f"{kb:.0f} KB"
        ext = os.path.splitext(self.path)[1].lstrip(".").upper()
        return f"{self.thumb.width()} × {self.thumb.height()}  ·  {ext}  ·  {s}"

    # ------------------------------------------------------------------ mouse: swipe to dismiss / drag file out
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.press = e.globalPos()
            self.origin = self.pos()
            self.mode = None
        elif e.button() == Qt.RightButton:
            self.dismiss()

    def mouseMoveEvent(self, e):
        if self.press is None or not (e.buttons() & Qt.LeftButton):
            return
        d = e.globalPos() - self.press
        if self.mode is None:
            if abs(d.x()) > px(10) and abs(d.x()) > abs(d.y()) and d.x() * self.edge > 0:
                self.mode = "swipe"
                if self._pos_anim:
                    self._pos_anim.stop()
            elif d.manhattanLength() > px(12) and os.path.exists(self.path):
                self.mode = "drag"
                self._start_drag()
                return
        if self.mode == "swipe":
            dx = d.x() if d.x() * self.edge > 0 else d.x() * 0.25
            self.move(self.origin.x() + dx, self.origin.y())
            self.setWindowOpacity(max(0.25, 1.0 - abs(dx) / (self.cw * 0.9)))

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self.press is None:
            return
        mode, self.press = self.mode, None
        if mode == "swipe":
            dx = self.pos().x() - self.origin.x()
            if abs(dx) > self.cw * 0.35:
                self.dismiss(self.edge)
            else:
                self.animate_to(self.origin, 260, QEasingCurve.OutBack)
                o = QPropertyAnimation(self, b"windowOpacity", self)
                o.setDuration(200)
                o.setEndValue(1.0)
                o.start()
                self._o = o
        elif mode is None:
            self.action.emit("edit" if self.kind == "image" else "open", self)
        self.mode = None

    def _start_drag(self):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(self.path)])
        d = QDrag(self)
        d.setMimeData(mime)
        d.setPixmap(QPixmap.fromImage(self.thumb.scaledToWidth(px(150), Qt.SmoothTransformation)))
        self.timer_anim.stop()
        if d.exec_(Qt.CopyAction) == Qt.CopyAction:
            self.dismiss()
        self.mode = None
        self.press = None


class QuickAccessManager:
    def __init__(self, on_action, get_settings):
        self.cards = []
        self.on_action = on_action
        self.cfg = get_settings          # callable -> settings dict
        self.recent = []                 # closed cards (for "restore")
        self.hidden = False

    # ------------------------------------------------------------------ add / remove
    def add(self, thumb, path, kind, seconds=None):
        c = self.cfg()
        pos = c.get("quick_access_pos", "bottom-left")
        card_screen = QGuiApplication.screenAt(self._cursor()) or QGuiApplication.primaryScreen()
        edge = -1 if pos.endswith("left") else 1
        card = QuickAccessCard(thumb, path, kind, c["quick_access_seconds"] if seconds is None else seconds,
                               c.get("quick_access_size", "medium"), edge, c.get("quick_access_info", True))
        card.screen_ref = card_screen
        card.action.connect(self._action)
        card.closed.connect(self._closed)
        self.hidden = False
        for k in self.cards:
            k.setWindowOpacity(1.0)
        self.cards.append(card)
        self._remember = (thumb, path, kind)
        targets = self._targets()
        card.slide_in(targets[card])
        for other, t in targets.items():
            if other is not card:
                other.animate_to(t)
        return card

    def _cursor(self):
        from PyQt5.QtGui import QCursor
        return QCursor.pos()

    def _action(self, name, card):
        if name == "close":
            card.dismiss()
        else:
            self.on_action(name, card)

    def _closed(self, card):
        if card in self.cards:
            self.cards.remove(card)
            self.recent.append((card.thumb, card.path, card.kind))
            self.recent = self.recent[-12:]
        for other, t in self._targets().items():
            if not other.dismissing:
                other.animate_to(t)

    def restore_last(self):
        """Bring back the most recently closed overlay."""
        while self.recent:
            thumb, path, kind = self.recent.pop()
            if os.path.exists(path):
                self.add(thumb, path, kind)
                return True
        return False

    def toggle_hidden(self):
        """Temporarily hide / show every overlay."""
        self.hidden = not self.hidden
        for c in self.cards:
            c.timer_anim.stop() if self.hidden else None
            o = QPropertyAnimation(c, b"windowOpacity", c)
            o.setDuration(200)
            o.setEndValue(0.0 if self.hidden else 1.0)
            o.start()
            c._toggle_anim = o
            if self.hidden:
                c.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            else:
                c.setAttribute(Qt.WA_TransparentForMouseEvents, False)

    # ------------------------------------------------------------------ layout
    def _targets(self):
        pos = self.cfg().get("quick_access_pos", "bottom-left")
        top = pos.startswith("top")
        left = pos.endswith("left")
        res = {}
        by_screen = {}
        for c in self.cards:
            by_screen.setdefault(id(getattr(c, "screen_ref", None)), []).append(c)
        for cards in by_screen.values():
            scr = getattr(cards[0], "screen_ref", None) or QGuiApplication.primaryScreen()
            g = scr.availableGeometry()
            margin = px(14) - px(PAD)
            y = g.top() + px(14) - px(PAD) if top else g.bottom() - px(14) + px(PAD)
            for c in (cards if top else reversed(cards)):
                x = g.left() + margin if left else g.right() - c.width() - margin
                if top:
                    res[c] = QPoint(x, y)
                    y += c.height() - px(PAD) * 2 + px(10)
                else:
                    y -= c.height()
                    res[c] = QPoint(x, y)
                    y += px(PAD) * 2 - px(10)
        return res

    def layout(self):
        for c, t in self._targets().items():
            c.animate_to(t)
