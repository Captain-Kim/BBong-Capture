"""Screen recording to MP4 / GIF plus the on-screen recording UI."""
import time

import cv2
import mss
import numpy as np
from PIL import Image
from PyQt5.QtCore import QRect, QRectF, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QWidget

from . import winutil
from .theme import icon, px


from .fonts import family as _fam  # noqa: E402


class Recorder(QThread):
    finished_file = pyqtSignal(str, bool)  # path, ok

    GIF_MAX_SECONDS = 60
    GIF_MAX_WIDTH = 800

    def __init__(self, rect, path, gif=False, fps=30, show_cursor=True, show_clicks=True):
        super().__init__()
        self.rect = QRect(rect.x(), rect.y(), rect.width() // 2 * 2, rect.height() // 2 * 2)
        self.path = path
        self.gif = gif
        self.fps = fps
        self.show_cursor = show_cursor
        self.show_clicks = show_clicks
        self._stop = False
        self._cancel = False
        self.paused = False
        self.elapsed = 0.0

    def stop(self):
        self._stop = True

    def cancel(self):
        self._cancel = True
        self._stop = True

    def _draw_pointer(self, frame):
        x, y = winutil.cursor_pos()
        x -= self.rect.x()
        y -= self.rect.y()
        if not (0 <= x < frame.shape[1] and 0 <= y < frame.shape[0]):
            return
        if self.show_clicks and (winutil.button_down(0x01) or winutil.button_down(0x02)):
            overlay = frame.copy()
            cv2.circle(overlay, (x, y), 22, (0, 200, 255), -1, cv2.LINE_AA)
            cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)
        if self.show_cursor:
            pts = np.array([[x, y], [x, y + 17], [x + 4, y + 13], [x + 7, y + 20], [x + 10, y + 19],
                            [x + 7, y + 12], [x + 12, y + 12]], np.int32)
            cv2.fillPoly(frame, [pts], (255, 255, 255), cv2.LINE_AA)
            cv2.polylines(frame, [pts], True, (0, 0, 0), 1, cv2.LINE_AA)

    def run(self):
        r = self.rect
        region = {"left": r.x(), "top": r.y(), "width": r.width(), "height": r.height()}
        fps = self.fps
        period = 1.0 / fps
        writer = None
        frames = []
        try:
            with mss.mss() as sct:
                if not self.gif:
                    writer = cv2.VideoWriter(self.path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (r.width(), r.height()))
                    if not writer.isOpened():
                        raise RuntimeError("cannot open video writer")
                start = time.perf_counter()
                paused_total = 0.0
                pause_began = None
                written = 0
                last_frame = None
                while not self._stop:
                    now = time.perf_counter()
                    if self.paused:
                        if pause_began is None:
                            pause_began = now
                        time.sleep(0.05)
                        continue
                    if pause_began is not None:
                        paused_total += now - pause_began
                        pause_began = None
                    t = now - start - paused_total
                    self.elapsed = t
                    if self.gif and t > self.GIF_MAX_SECONDS:
                        break
                    frame = np.array(sct.grab(region))[:, :, :3].copy()
                    if self.show_cursor or self.show_clicks:
                        self._draw_pointer(frame)
                    last_frame = frame
                    target = int(t / period) + 1
                    if self.gif:
                        if written < target:
                            frames.append(self._to_gif_frame(frame))
                            written += 1
                    else:
                        while written < target:
                            writer.write(frame)
                            written += 1
                    sleep = period - (time.perf_counter() - now)
                    if sleep > 0:
                        time.sleep(sleep)
                if writer:
                    writer.release()
                    writer = None
            if self._cancel:
                self._remove()
                self.finished_file.emit(self.path, False)
                return
            if self.gif:
                if not frames:
                    raise RuntimeError("no frames")
                frames[0].save(self.path, save_all=True, append_images=frames[1:], duration=int(1000 / fps),
                               loop=0, optimize=False, disposal=2)
            self.finished_file.emit(self.path, True)
        except Exception:
            if writer:
                writer.release()
            self._remove()
            self.finished_file.emit(self.path, False)

    def _to_gif_frame(self, bgr):
        h, w = bgr.shape[:2]
        if w > self.GIF_MAX_WIDTH:
            bgr = cv2.resize(bgr, (self.GIF_MAX_WIDTH, int(h * self.GIF_MAX_WIDTH / w)), interpolation=cv2.INTER_AREA)
        return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).quantize(colors=160, method=Image.Quantize.FASTOCTREE)

    def _remove(self):
        import os
        try:
            os.remove(self.path)
        except OSError:
            pass


class RegionFrame(QWidget):
    """Click-through border drawn just outside the recorded region."""
    PAD = 3

    def __init__(self, rect):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(rect.adjusted(-self.PAD, -self.PAD, self.PAD, self.PAD))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setPen(QPen(QColor(255, 69, 58), self.PAD * 2, Qt.SolidLine))
        p.drawRect(self.rect())

    def show(self):
        super().show()
        winutil.exclude_from_capture(self)


class RecordBar(QWidget):
    stop_clicked = pyqtSignal()
    pause_toggled = pyqtSignal(bool)
    cancel_clicked = pyqtSignal()

    def __init__(self, recorder, rect):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.recorder = recorder
        lay = QHBoxLayout(self)
        lay.setContentsMargins(px(14), px(8), px(10), px(8))
        lay.setSpacing(px(8))
        self.dot = QLabel("●")
        self.dot.setStyleSheet("color:#ff453a;font-size:12pt;")
        self.time = QLabel("00:00")
        f = QFont(_fam(), 11)
        f.setBold(True)
        self.time.setFont(f)
        self.time.setFixedWidth(px(56))                  # fixed width: digits changing never shifts the buttons
        self.dot.setFixedWidth(px(18))                   # reserve the dot's space even while it is "off"
        self.dot_fx = QGraphicsOpacityEffect(self.dot)   # blink by opacity, never by hiding (hiding re-flows the layout)
        self.dot.setGraphicsEffect(self.dot_fx)
        lay.addWidget(self.dot)
        lay.addWidget(self.time)
        self.pause_btn = self._btn("pause", "일시정지")
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self._pause)
        stop = self._btn("stop", "중지 및 저장")
        stop.clicked.connect(self.stop_clicked)
        cancel = self._btn("trash", "녹화 취소")
        cancel.clicked.connect(self.cancel_clicked)
        for b in (self.pause_btn, stop, cancel):
            lay.addWidget(b)
        self.adjustSize()
        self._place(rect)
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(200)
        self._blink = 0

    def _btn(self, name, tip):
        b = QPushButton()
        b.setIcon(icon(name))
        b.setToolTip(tip)
        b.setFixedSize(px(30), px(30))
        b.setStyleSheet("QPushButton{background:#3a3a3c;border-radius:15px;padding:0}QPushButton:hover{background:#555}"
                        "QPushButton:checked{background:#ff9f0a}")
        return b

    def _pause(self, on):
        self.recorder.paused = on
        self.pause_toggled.emit(on)

    def _place(self, rect):
        from PyQt5.QtGui import QGuiApplication
        scr = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
        g = scr.geometry()
        w, h = self.width(), self.height()
        x = min(max(g.left() + 4, rect.center().x() - w // 2), g.right() - w - 4)
        y = rect.bottom() + px(14)
        if y + h > g.bottom() - 4:
            y = rect.top() - h - px(14)
        if y < g.top() + 4:
            y = g.bottom() - h - px(60)  # region fills screen: float near the bottom (hidden from capture)
        self.move(x, y)

    def _tick(self):
        s = int(self.recorder.elapsed)
        self.time.setText(f"{s // 60:02d}:{s % 60:02d}")
        self._blink += 1
        self.dot_fx.setOpacity(1.0 if (self.recorder.paused or self._blink % 4 < 3) else 0.0)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(QColor(28, 28, 30, 240))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), self.height() / 2, self.height() / 2)

    def show(self):
        super().show()
        winutil.exclude_from_capture(self)


class CountdownWidget(QWidget):
    finished = pyqtSignal()
    aborted = pyqtSignal()

    def __init__(self, seconds, center):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.n = seconds
        s = px(130)
        self.setGeometry(center.x() - s // 2, center.y() - s // 2, s, s)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._step)

    def go(self):
        self.show()
        winutil.exclude_from_capture(self)
        winutil.force_foreground(self)
        self.timer.start(1000)

    def _step(self):
        self.n -= 1
        if self.n <= 0:
            self.timer.stop()
            self.hide()
            self.finished.emit()
            self.close()
        else:
            self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.timer.stop()
            self.hide()
            self.aborted.emit()
            self.close()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(28, 28, 30, 225))
        p.drawEllipse(self.rect().adjusted(4, 4, -4, -4))
        f = QFont(_fam(), 44)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(self.rect(), Qt.AlignCenter, str(self.n))
