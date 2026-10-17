"""Full-screen overlay for picking an area / window / colour, with smooth fades."""
from PyQt5.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, QRectF, QSize, Qt, QVariantAnimation, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen, QRegion
from PyQt5.QtWidgets import QApplication, QWidget

from .winutil import force_foreground


from .fonts import family as _fam  # noqa: E402


class SelectionOverlay(QWidget):
    done = pyqtSignal(QRect)   # global (virtual-desktop) coordinates
    cancelled = pyqtSignal()
    picked = pyqtSignal(QColor)

    MAG_N = 15      # source pixels shown in magnifier
    MAG_ZOOM = 9

    def __init__(self, shot, origin, mode="area", windows=None, hint=None, crosshair=True, magnifier=True,
                 freeze=True, ratio=None, fixed_size=None, initial=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.shot = shot
        self.origin = QPoint(origin)
        self.mode = mode  # "area" | "window" | "color"
        self.windows = windows or []
        self.crosshair, self.magnifier, self.freeze = crosshair, magnifier, freeze
        self.ratio = ratio                    # width / height or None
        self.fixed_size = fixed_size          # QSize or None
        self.initial = initial                # global QRect remembered from the last capture
        self.hint = hint or {
            "window": "캡처할 창을 클릭하세요  ·  Esc: 취소",
            "color": "색을 추출할 위치를 클릭하세요  ·  Esc: 취소",
        }.get(mode) or ("클릭하면 지정한 크기로 캡처  ·  Esc: 취소" if fixed_size else
                        "드래그로 영역 선택  ·  클릭하면 창 선택  ·  Space: 이동  ·  Shift: 정사각형  ·  Esc: 취소")
        self.setGeometry(QRect(self.origin, shot.size()))
        if not freeze or mode == "color":
            pass
        if not freeze and mode != "color":
            self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.pressing = False
        self.anchor = QPoint()
        self.cur = QPoint(-100, -100)
        self.last = QPoint()
        self.space = False
        self.sel = QRect()
        self.hover_win = QRect()
        self._finished = False
        self.dim_t = 0.0
        self.fade = QVariantAnimation(self)
        self.fade.setDuration(170)
        self.fade.setStartValue(0.0)
        self.fade.setEndValue(1.0)
        self.fade.setEasingCurve(QEasingCurve.OutCubic)
        self.fade.valueChanged.connect(self._fade_changed)

    # ------------------------------------------------------------------ helpers
    def start(self):
        self.setWindowOpacity(1.0)
        self.show()
        force_foreground(self)
        self.fade.start()

    def _fade_changed(self, v):
        self.dim_t = float(v)
        self.update()

    def _window_at(self, p):
        g = p + self.origin
        for _, _, r in self.windows:
            if r.contains(g):
                return r.translated(-self.origin).intersected(self.rect())
        return QRect()

    def _apply_ratio(self, a, dx, dy):
        if not self.ratio:
            return dx, dy
        w = max(abs(dx), abs(dy) * self.ratio)
        h = w / self.ratio
        return (w if dx >= 0 else -w), (h if dy >= 0 else -h)

    def _compute_sel(self):
        if self.fixed_size:
            s = self.fixed_size
            r = QRect(0, 0, s.width(), s.height())
            r.moveCenter(self.cur)
            return self._clamp_rect(r)
        dx, dy = self.cur.x() - self.anchor.x(), self.cur.y() - self.anchor.y()
        if QApplication.keyboardModifiers() & Qt.ShiftModifier:
            m = max(abs(dx), abs(dy))
            dx = m if dx >= 0 else -m
            dy = m if dy >= 0 else -m
        else:
            dx, dy = self._apply_ratio(self.anchor, dx, dy)
        end = QPoint(self.anchor.x() + int(dx), self.anchor.y() + int(dy))
        return QRect(self.anchor, end).normalized().intersected(self.rect())

    def _clamp_rect(self, r):
        b = self.rect()
        if r.left() < b.left():
            r.moveLeft(b.left())
        if r.top() < b.top():
            r.moveTop(b.top())
        if r.right() > b.right():
            r.moveRight(b.right())
        if r.bottom() > b.bottom():
            r.moveBottom(b.bottom())
        return r

    def _finish(self, local_rect):
        if self._finished:
            return
        self._finished = True
        r = QRect(local_rect).translated(self.origin)
        self._leave(lambda: self.done.emit(r))

    def _cancel(self):
        if self._finished:
            return
        self._finished = True
        self._leave(self.cancelled.emit)

    def _leave(self, emit):
        """Emit immediately; fade out (frozen screenshots only) so the hand-off feels smooth."""
        if self.freeze and self.mode != "color":
            emit()
            a = QPropertyAnimation(self, b"windowOpacity", self)
            a.setDuration(150)
            a.setStartValue(1.0)
            a.setEndValue(0.0)
            a.setEasingCurve(QEasingCurve.InCubic)
            a.finished.connect(self._really_close)
            self._out = a
            a.start()
        else:
            self.hide()
            emit()
            self._really_close()

    def _really_close(self):
        self.hide()
        self.close()

    # ------------------------------------------------------------------ events
    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self._cancel()
        elif e.button() == Qt.LeftButton:
            if self.mode == "color":
                self._pick(e.pos())
            elif self.mode == "area":
                if self.fixed_size:
                    self.cur = e.pos()
                    self._finish(self._compute_sel())
                    return
                self.pressing = True
                self.anchor = e.pos()
                self.cur = e.pos()
                self.last = e.pos()
                self.sel = QRect(e.pos(), e.pos())
                self.update()

    def _pick(self, pos):
        c = QColor(self.shot.pixel(pos.x(), pos.y())) if self.shot.rect().contains(pos) else QColor(0, 0, 0)
        self._finished = True
        self.picked.emit(c)
        self._leave(lambda: None)

    def mouseMoveEvent(self, e):
        self.cur = e.pos()
        if self.pressing:
            if self.space:
                self.anchor += e.pos() - self.last
            self.last = e.pos()
            self.sel = self._compute_sel()
        elif self.fixed_size and self.mode == "area":
            self.sel = self._compute_sel()
        else:
            self.hover_win = self._window_at(e.pos())
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self.mode == "window":
            if not self.hover_win.isNull():
                self._finish(self.hover_win)
            return
        if not self.pressing:
            return
        self.pressing = False
        sel = self._compute_sel()
        if sel.width() < 4 and sel.height() < 4:
            w = self._window_at(e.pos())
            if not w.isNull() and not self.ratio:
                self._finish(w)
            else:
                self.update()
            return
        self._finish(sel)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._cancel()
        elif e.key() == Qt.Key_Space:
            self.space = True
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self.initial is not None and self.sel.isNull():
                self._finish(self.initial.translated(-self.origin).intersected(self.rect()))
            elif not self.sel.isNull() and self.sel.width() > 3:
                self._finish(self.sel)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Space:
            self.space = False

    # ------------------------------------------------------------------ painting
    def _highlight(self):
        if self.mode == "window" or (self.mode == "area" and not self.pressing and not self.fixed_size):
            return self.hover_win
        return self.sel

    def paintEvent(self, _):
        p = QPainter(self)
        if self.freeze or self.mode == "color":
            p.drawImage(0, 0, self.shot)
        else:
            p.setCompositionMode(QPainter.CompositionMode_Source)
            p.fillRect(self.rect(), QColor(0, 0, 0, 1))   # near-invisible so the window still receives the mouse
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        if self.mode != "color":
            hl = self._highlight()
            dim = QColor(0, 0, 0, int(125 * self.dim_t))
            if hl.isNull() or hl.width() <= 0:
                p.fillRect(self.rect(), dim)
            else:
                p.setClipRegion(QRegion(self.rect()).subtracted(QRegion(hl)))
                p.fillRect(self.rect(), dim)
                p.setClipping(False)
                if not self.freeze:
                    p.setCompositionMode(QPainter.CompositionMode_Source)
                    p.fillRect(hl, QColor(0, 0, 0, 1))
                    p.setCompositionMode(QPainter.CompositionMode_SourceOver)
                if self.pressing or self.fixed_size:
                    p.setPen(QPen(QColor("white"), 1.5))
                    p.setBrush(Qt.NoBrush)
                    p.drawRect(hl.adjusted(0, 0, -1, -1))
                else:
                    p.setPen(QPen(QColor(10, 132, 255), 2))
                    p.setBrush(QColor(10, 132, 255, 55))
                    p.drawRoundedRect(QRectF(hl).adjusted(1, 1, -1, -1), 8, 8)
                self._draw_size(p, hl)
            if self.initial is not None and self.sel.isNull() and not self.pressing and self.mode == "area":
                r = self.initial.translated(-self.origin)
                p.setPen(QPen(QColor(255, 255, 255, 170), 1.5, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(r)
                self._pill(p, "Enter: 이전 영역으로 캡처", r.x(), r.bottom() + 8)
        if self.mode in ("area", "color") and self.crosshair and not self.cur.isNull():
            p.setPen(QPen(QColor(255, 255, 255, 110), 1, Qt.DashLine))
            p.drawLine(self.cur.x(), 0, self.cur.x(), self.height())
            p.drawLine(0, self.cur.y(), self.width(), self.cur.y())
        if self.magnifier and self.rect().contains(self.cur):
            self._draw_magnifier(p)
        self._draw_hint(p)

    def _pill(self, p, text, x, y):
        f = QFont(_fam(), 9)
        f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        w, h = fm.horizontalAdvance(text) + 22, fm.height() + 10
        x = max(2, min(x, self.width() - w - 2))
        y = max(2, min(y, self.height() - h - 2))
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(QColor(28, 28, 32, 232))
        p.drawRoundedRect(QRectF(x, y, w, h), h / 2, h / 2)
        p.setPen(QColor("white"))
        p.drawText(QRect(x, y, w, h), Qt.AlignCenter, text)

    def _draw_size(self, p, r):
        self._pill(p, f"{r.width()} × {r.height()}", r.x(), r.y() - 36 if r.y() > 40 else r.y() + 8)

    def _draw_hint(self, p):
        scr = QGuiApplication.screenAt(self.cur + self.origin) or QGuiApplication.primaryScreen()
        g = scr.geometry().translated(-self.origin)
        p.setFont(QFont(_fam(), 9))
        w = p.fontMetrics().horizontalAdvance(self.hint) + 30
        self._pill(p, self.hint, g.center().x() - w // 2, g.top() + 26 - int(14 * (1 - self.dim_t)))

    def _draw_magnifier(self, p):
        n, z = self.MAG_N, self.MAG_ZOOM
        size = n * z
        cx, cy = self.cur.x(), self.cur.y()
        x, y = cx + 26, cy + 26
        if x + size > self.width() - 4:
            x = cx - 26 - size
        if y + size + 48 > self.height() - 4:
            y = cy - 26 - size - 48
        src = QRect(cx - n // 2, cy - n // 2, n, n)
        p.save()
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        p.setRenderHint(QPainter.Antialiasing)
        from PyQt5.QtGui import QPainterPath
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(x, y, size, size), 18, 18)
        p.setClipPath(clip)
        p.fillRect(QRect(x, y, size, size), QColor(20, 20, 20))
        p.drawImage(QRect(x, y, size, size), self.shot, src)
        p.setClipping(False)
        p.restore()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 230), 2))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(x, y, size, size), 18, 18)
        p.setPen(QPen(QColor(10, 132, 255), 1.5))
        p.drawRect(QRect(x + (n // 2) * z, y + (n // 2) * z, z, z))
        c = QColor(self.shot.pixel(cx, cy)) if self.shot.rect().contains(cx, cy) else QColor(0, 0, 0)
        gx, gy = cx + self.origin.x(), cy + self.origin.y()
        self._pill(p, f"{gx}, {gy}   {c.name().upper()}", x, y + size + 8)
