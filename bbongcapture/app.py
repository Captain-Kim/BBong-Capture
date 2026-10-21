"""Application controller: tray icon, global hotkeys and capture workflows."""
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QObject, QPoint, QRect, QRectF, Qt, QTimer, QUrl, QMimeData, pyqtSignal
from PyQt5.QtGui import QColor, QCursor, QGuiApplication, QImage, QPainter, QPainterPath, QPixmap
from PyQt5.QtWidgets import (QAction, QApplication, QComboBox, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
                             QSpinBox, QSystemTrayIcon, QWidget)
from PyQt5.QtCore import QSize

from . import histstore, ocr, winutil
from .background import BgSpec, compose, round_corners
from .editor import EditorWindow
from .history import HistoryWindow, video_thumb
from .hotkeys import HotkeyManager
from .overlay import SelectionOverlay
from .pin import PinWindow
from .prefs import PrefsDialog
from .quickaccess import QuickAccessManager
from .recorder import CountdownWidget, RecordBar, Recorder, RegionFrame
from .scrolling import ScrollCapture
from .settings import HOTKEY_LABELS, settings
from .theme import C, app_icon, icon, paint_glass, paint_pill, px, round_menu


def debug_log(msg):
    """Append to %APPDATA%\\BBongCapture\\debug.log (helps diagnose hotkey / multi-instance problems)."""
    try:
        from .settings import data_dir
        p = data_dir() / "debug.log"
        if p.exists() and p.stat().st_size > 200_000:
            p.write_text("", encoding="utf-8")
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%H:%M:%S.%f}"[:-3] + f" pid={os.getpid()} {msg}\n")
    except Exception:
        pass


class HotkeyBridge(QObject):
    triggered = pyqtSignal(str)


class AllInOneBar(QWidget):
    """All-in-One: every capture mode on one bar, plus size / aspect-ratio lock and 'previous area'."""
    chosen = pyqtSignal(str, dict)

    ITEMS = [("area", "area", "영역"), ("window", "window", "창"), ("fullscreen", "fullscreen", "전체 화면"),
             ("scrolling", "scroll", "스크롤"), ("ocr", "ocr", "텍스트"), ("record", "record", "녹화"),
             ("record_gif", "gif", "GIF")]
    RATIOS = {"자유": None, "1:1": 1.0, "4:3": 4 / 3, "3:2": 3 / 2, "16:9": 16 / 9, "9:16": 9 / 16, "2:1": 2.0}

    def __init__(self, has_last):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowOpacity(0.0)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(px(14), px(12), px(14), px(12))
        outer.setSpacing(px(4))
        self.setStyleSheet("QPushButton{background:transparent;border:none;border-radius:%dpx;padding:%dpx %dpx;color:#e8e8ea;}"
                           "QPushButton:hover{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #4aa3ff,stop:1 #0a84ff);color:white;}"
                           "QSpinBox,QComboBox{background:rgba(255,255,255,18);border:1px solid rgba(255,255,255,30);"
                           "border-radius:%dpx;color:white;padding:%dpx %dpx;}QLabel{color:#9a9aa2;}"
                           % (px(16), px(8), px(10), px(9), px(4), px(6)))
        self.opts = {}
        for key, ic, text in self.ITEMS:
            btn = QPushButton(text)
            btn.setIcon(icon(ic, "#e8e8ea"))
            btn.setIconSize(QSize(px(20), px(20)))
            btn.clicked.connect(lambda _, k=key: self._pick(k))
            outer.addWidget(btn)
        sep = QWidget()
        sep.setFixedSize(1, px(26))
        sep.setStyleSheet("background:rgba(255,255,255,40);")
        outer.addWidget(sep)
        outer.addWidget(QLabel("크기"))
        self.w = QSpinBox()
        self.w.setRange(0, 20000)
        self.w.setSpecialValueText("자동")
        self.h = QSpinBox()
        self.h.setRange(0, 20000)
        self.h.setSpecialValueText("자동")
        for sp in (self.w, self.h):
            sp.setFixedWidth(px(72))
            sp.setButtonSymbols(QSpinBox.NoButtons)
        outer.addWidget(self.w)
        outer.addWidget(QLabel("×"))
        outer.addWidget(self.h)
        self.ratio = QComboBox()
        self.ratio.addItems(list(self.RATIOS))
        self.ratio.setCurrentText(settings.data.get("aio_ratio", "자유"))
        self.ratio.setToolTip("비율 고정")
        outer.addWidget(self.ratio)
        self.last_btn = QPushButton("이전 영역")
        self.last_btn.setEnabled(has_last)
        self.last_btn.clicked.connect(lambda: self._pick("area", initial=True))
        outer.addWidget(self.last_btn)
        close = QPushButton()
        close.setIcon(icon("close", "#e8e8ea"))
        close.setIconSize(QSize(px(14), px(14)))
        close.clicked.connect(self.close_animated)
        outer.addWidget(close)
        self.adjustSize()

    def paintEvent(self, _):
        paint_pill(self, px(30))

    def _pick(self, k, initial=False):
        opts = {}
        r = self.RATIOS.get(self.ratio.currentText())
        settings.data["aio_ratio"] = self.ratio.currentText()
        if r:
            opts["ratio"] = r
        if self.w.value() > 0 and self.h.value() > 0:
            opts["fixed_size"] = QSize(self.w.value(), self.h.value())
        if initial:
            opts["initial"] = True
        self.hide()
        QTimer.singleShot(120, lambda: self.chosen.emit(k, opts))

    def popup(self):
        scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = scr.geometry()
        self._target = QPoint(g.center().x() - self.width() // 2, g.bottom() - self.height() - px(90))
        self.move(self._target + QPoint(0, px(24)))
        self.show()
        winutil.force_foreground(self)
        from PyQt5.QtCore import QEasingCurve, QParallelAnimationGroup, QPropertyAnimation
        g = QParallelAnimationGroup(self)
        a = QPropertyAnimation(self, b"pos")
        a.setDuration(260)
        a.setStartValue(self._target + QPoint(0, px(24)))
        a.setEndValue(self._target)
        a.setEasingCurve(QEasingCurve.OutCubic)
        o = QPropertyAnimation(self, b"windowOpacity")
        o.setDuration(220)
        o.setStartValue(0.0)
        o.setEndValue(1.0)
        g.addAnimation(a)
        g.addAnimation(o)
        self._anim = g
        g.start()

    def close_animated(self):
        from PyQt5.QtCore import QPropertyAnimation
        o = QPropertyAnimation(self, b"windowOpacity", self)
        o.setDuration(160)
        o.setStartValue(self.windowOpacity())
        o.setEndValue(0.0)
        o.finished.connect(self.close)
        self._out = o
        o.start()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close_animated()


class Controller(QObject):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.pins, self.editors = [], []
        self.overlay = None
        self.recorder = None
        self.record_ui = []
        self.scroller = None
        self.scroll_bar = None
        self.scroll_preview = None
        self.busy = False
        self.history = None
        self.prefs = None
        self.allinone = None
        self.countdown = None
        self._last_dispatch = {}
        self._overlay_closed_at = 0.0
        self.qa = QuickAccessManager(self._qa_action, lambda: settings.data)
        self.hotkeys = HotkeyManager(self.dispatch)
        app.installNativeEventFilter(self.hotkeys)
        self._build_tray()
        self.register_hotkeys()

    # ------------------------------------------------------------------ tray / hotkeys
    def _build_tray(self):
        self.tray = QSystemTrayIcon(app_icon(), self.app)
        self.tray.setToolTip("BBong Capture")
        m = round_menu(QMenu())
        self.menu = m

        def add(text, key, ic, menu=None):
            a = QAction(icon(ic), text, menu or m)
            a.triggered.connect(lambda: QTimer.singleShot(150, lambda: self.dispatch(key)))
            (menu or m).addAction(a)
            return a

        def toggle(menu, text, key):
            a = QAction(text, menu)
            a.setCheckable(True)
            a.setChecked(bool(settings.data.get(key)))
            a.toggled.connect(lambda v: (settings.data.__setitem__(key, v), settings.save()))
            menu.addAction(a)

        def choice(menu, items, key, after=None):
            from PyQt5.QtWidgets import QActionGroup
            g = QActionGroup(menu)
            for label, val in items:
                a = QAction(label, menu)
                a.setCheckable(True)
                a.setChecked(settings.data.get(key) == val)
                a.triggered.connect(lambda _, v=val: (settings.data.__setitem__(key, v), settings.save(), after() if after else None))
                g.addAction(a)
                menu.addAction(a)

        add("올인원", "all_in_one", "allinone")
        m.addSeparator()
        add("영역 캡처", "area", "area")
        add("이전 영역 다시 캡처", "repeat_area", "area")
        add("전체 화면 캡처", "fullscreen", "fullscreen")
        add("창 캡처", "window", "window")
        add("스크롤 캡처", "scrolling", "scroll")
        t = round_menu(m.addMenu(icon("timer"), "타이머 전체 화면 캡처"))
        for s in (3, 5, 10):
            t.addAction(f"{s}초", lambda s=s: self.self_timer(s))
        m.addSeparator()
        co = round_menu(m.addMenu(icon("camera"), "캡처 옵션"))
        toggle(co, "십자선 표시", "show_crosshair")
        toggle(co, "돋보기 표시", "show_magnifier")
        toggle(co, "화면 정지 (움직이는 대상 캡처)", "freeze_screen")
        co.addSeparator()
        toggle(co, "창 캡처: 배경 입히기", "window_background")
        toggle(co, "창 캡처: 모서리 둥글게 (투명)", "window_round_corners")
        toggle(co, "창 캡처: 그림자", "window_shadow")
        qa = round_menu(m.addMenu(icon("grid"), "퀵 액세스 오버레이"))
        pos = round_menu(qa.addMenu("위치"))
        choice(pos, [("왼쪽 아래", "bottom-left"), ("오른쪽 아래", "bottom-right"), ("왼쪽 위", "top-left"), ("오른쪽 위", "top-right")],
               "quick_access_pos", self.qa.layout)
        sz = round_menu(qa.addMenu("크기"))
        choice(sz, [("작게", "small"), ("보통", "medium"), ("크게", "large")], "quick_access_size")
        ac = round_menu(qa.addMenu("자동 닫기"))
        choice(ac, [("사용 안 함", 0), ("3초", 3), ("5초", 5), ("7초", 7), ("10초", 10), ("30초", 30)], "quick_access_seconds")
        toggle(qa, "파일 정보 표시", "quick_access_info")
        toggle(qa, "짬뽕이 알림 (캡처완료!)", "buddy_toast")
        qa.addSeparator()
        qa.addAction(icon("restore"), "닫은 오버레이 복원", self.restore_overlay)
        qa.addAction(icon("eye"), "오버레이 숨기기 / 보이기", self.qa.toggle_hidden)
        m.addSeparator()
        add("캡처 기록", "history", "history")
        a = QAction(icon("pin"), "클립보드 이미지 고정", m)
        a.triggered.connect(self.pin_clipboard)
        m.addAction(a)
        a = QAction(icon("unlock"), "고정 화면 잠금 해제 / 잠금", m)
        a.triggered.connect(self.toggle_pin_lock)
        m.addAction(a)
        a = QAction(icon("edit"), "클립보드 이미지 편집", m)
        a.triggered.connect(self.edit_clipboard)
        m.addAction(a)
        a = QAction(icon("folder"), "저장 폴더 열기", m)
        a.triggered.connect(lambda: os.startfile(str(settings.save_dir())))
        m.addAction(a)
        m.addSeparator()
        add("화면 녹화 (MP4)", "record", "record")
        add("GIF 녹화", "record_gif", "gif")
        add("텍스트 캡처 (OCR)", "ocr", "ocr")
        m.addSeparator()
        a = QAction(icon("settings"), "환경설정…", m)
        a.triggered.connect(self.show_prefs)
        m.addAction(a)
        q = QAction("종료", m)
        q.triggered.connect(self.quit)
        m.addAction(q)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self.dispatch("all_in_one") if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def register_hotkeys(self, attempt=0, pending=None):
        """Register every hotkey. A key that fails is retried for ~2s first: right after a restart the previous
        instance may still be shutting down and hold it for a moment."""
        if attempt == 0:
            self.hotkeys.unregister_all()
            pending = dict(settings["hotkeys"])
        failed = {}
        for key, combo in pending.items():
            if not combo:
                continue
            err = self.hotkeys.register(key, combo)
            debug_log(f"register {key}='{combo}' (try {attempt + 1}) -> {err or 'ok'}")
            if err:
                failed[key] = (combo, err)
        if failed and attempt < 5:
            QTimer.singleShot(400, lambda: self.register_hotkeys(attempt + 1, {k: c for k, (c, _) in failed.items()}))
            return
        if failed:
            lines = [f"{HOTKEY_LABELS.get(k, k)}  ({c})" for k, (c, _) in failed.items()]
            others = self._other_instances()
            if others:
                why = (f"이전에 실행한 BBong Capture(PID {', '.join(map(str, others))})가 아직 켜져 있어 단축키가 겹칩니다.\n"
                       "트레이 아이콘이 둘이면 이전 것을 종료하거나, 작업 관리자에서 BBongCapture를 종료한 뒤 다시 실행하세요.")
            else:
                why = "다른 프로그램이 이 단축키를 쓰고 있습니다. 환경설정 > 단축키에서 바꿀 수 있습니다."
            self.tray.showMessage("BBong Capture", why + "\n\n등록되지 않은 단축키:\n" + "\n".join(lines),
                                  QSystemTrayIcon.Warning, 10000)

    def _other_instances(self):
        """PIDs of other running BBong Capture processes (used only when registration fails)."""
        import subprocess
        try:
            cmd = ("Get-CimInstance Win32_Process | Where-Object { (($_.Name -match '^pythonw?\\.exe$' -and "
                   "$_.CommandLine -match 'main\\.py') -or $_.Name -eq 'BBongCapture.exe') -and $_.ProcessId -ne %d } | ForEach-Object { $_.ProcessId }" % os.getpid())
            out = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
                                 capture_output=True, text=True, timeout=8, creationflags=0x08000000).stdout
            return [int(x) for x in out.split() if x.isdigit()]
        except Exception:
            return []

    def dispatch(self, key):
        now = time.monotonic()
        # ignore bursts / repeats of the same trigger and anything right after a capture finished
        capture_like = key in ("area", "window", "fullscreen", "scrolling", "ocr", "record", "record_gif", "all_in_one", "repeat_area")
        if now - self._last_dispatch.get(key, 0) < 0.6 or (capture_like and now - self._overlay_closed_at < 0.6):
            debug_log(f"dispatch '{key}' ignored (debounce)")
            return
        self._last_dispatch[key] = now
        debug_log(f"dispatch '{key}'")
        # small delay so the hotkey's modifier keys are released before we grab the screen
        QTimer.singleShot(120, lambda: self._run(key))

    def _run(self, key, opts=None):
        opts = opts or {}
        fn = {
            "all_in_one": self.all_in_one, "area": lambda: self.capture_area(**opts),
            "fullscreen": self.capture_fullscreen, "window": self.capture_window, "scrolling": self.capture_scrolling,
            "ocr": self.capture_text, "record": lambda: self.toggle_recording(False),
            "record_gif": lambda: self.toggle_recording(True), "repeat_area": self.capture_previous_area,
            "history": self.show_history, "restore_overlay": self.restore_overlay,
            "toggle_overlays": self.qa.toggle_hidden, "pin_lock": self.toggle_pin_lock,
        }.get(key)
        if fn:
            fn()

    # ------------------------------------------------------------------ capture primitives
    def _own_hwnds(self):
        return {int(w.winId()) for w in QApplication.topLevelWidgets() if w.isVisible()}

    def _begin_capture(self):
        """Take the frozen desktop shot (optionally with desktop icons hidden)."""
        if self.busy:
            return None
        hid = False
        if settings["hide_desktop_icons"] and winutil.desktop_icons_visible():
            winutil.set_desktop_icons(False)
            hid = True
            QApplication.processEvents()
            time.sleep(0.25)
        shot, origin = winutil.grab_virtual()
        if hid:
            winutil.set_desktop_icons(True)
        return shot, origin

    def _pick(self, mode, callback, cancel=None, ratio=None, fixed_size=None, initial=None):
        if self.overlay is not None:
            return
        r = self._begin_capture()
        if r is None:
            return
        shot, origin = r
        windows = winutil.list_windows(exclude=self._own_hwnds())
        freeze = bool(settings["freeze_screen"])
        ov = SelectionOverlay(shot, origin, mode, windows, crosshair=bool(settings["show_crosshair"]),
                              magnifier=bool(settings["show_magnifier"]), freeze=freeze, ratio=ratio,
                              fixed_size=fixed_size, initial=initial)
        self.overlay = ov

        def done(rect):
            self.overlay = None
            self._overlay_closed_at = time.monotonic()
            if freeze:
                callback(rect, shot, origin)
            else:   # live mode: grab the screen as it is right now, after the overlay is gone
                def later():
                    s2, o2 = winutil.grab_virtual()
                    callback(rect, s2, o2)
                QTimer.singleShot(170, later)

        def cancelled():
            self.overlay = None
            self._overlay_closed_at = time.monotonic()
            if cancel:
                cancel()

        ov.done.connect(done)
        ov.cancelled.connect(cancelled)
        ov.start()

    def capture_area(self, ratio=None, fixed_size=None, initial=False):
        def cb(rect, shot, origin):
            settings["last_area"] = [rect.x(), rect.y(), rect.width(), rect.height()]
            settings.save()
            self.handle_image(shot.copy(rect.translated(-origin)), "area")

        last = QRect(*settings["last_area"]) if (initial and settings["last_area"]) else None
        self._pick("area", cb, ratio=ratio, fixed_size=fixed_size, initial=last)

    def capture_previous_area(self):
        a = settings["last_area"]
        if not a:
            return self.capture_area()
        self.handle_image(winutil.grab_rect(QRect(*a)), "area")

    def window_style(self, img):
        """Window screenshots: rounded transparent corners, optional background and shadow."""
        if settings["window_round_corners"]:
            img = round_corners(img.convertToFormat(QImage.Format_ARGB32_Premultiplied), px(8))
        if settings["window_background"]:
            last = settings.data.get("bg_last")
            spec = BgSpec.from_dict(last) if last else BgSpec(kind="gradient", gradient=0)
            if not spec.active() or spec.kind == "none":
                spec = BgSpec(kind="gradient", gradient=0)
            spec.shadow = bool(settings["window_shadow"])
            spec.radius = px(8) if settings["window_round_corners"] else spec.radius
            return compose(img, spec)
        if settings["window_shadow"] and settings["window_round_corners"]:
            spec = BgSpec(kind="transparent", padding=px(40), radius=px(8), shadow=True, shadow_blur=px(36))
            return compose(img, spec)
        return img

    def capture_window(self):
        def cb(rect, shot, origin):
            self.handle_image(self.window_style(shot.copy(rect.translated(-origin))), "window")

        self._pick("window", cb)

    def capture_fullscreen(self):
        r = self._begin_capture()
        if r is None:
            return
        shot, origin = r
        pos = QCursor.pos()
        for m in winutil.monitors():
            if m.contains(pos):
                return self.handle_image(shot.copy(m.translated(-origin)), "fullscreen")
        self.handle_image(shot, "fullscreen")

    def self_timer(self, seconds):
        c = CountdownWidget(seconds, QGuiApplication.primaryScreen().geometry().center())
        self.countdown = c
        c.finished.connect(lambda: QTimer.singleShot(150, self.capture_fullscreen))
        c.go()

    def all_in_one(self):
        if self.allinone is not None and self.allinone.isVisible():
            self.allinone.close_animated()
            return
        self.allinone = AllInOneBar(bool(settings["last_area"]))
        self.allinone.chosen.connect(lambda k, o: self._run(k, o))
        self.allinone.popup()

    # ------------------------------------------------------------------ after capture
    def _new_path(self, ext):
        name = datetime.now().strftime("BBongCapture %Y-%m-%d at %H.%M.%S")
        if settings["after_capture"].get("auto_save"):
            d = settings.save_dir()
        else:
            d = settings.temp_dir()
            cutoff = time.time() - 86400
            for f in d.iterdir():
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                except Exception:
                    pass
        p = d / f"{name}.{ext}"
        i = 2
        while p.exists():
            p = d / f"{name} ({i}).{ext}"
            i += 1
        return p

    def handle_image(self, img: QImage, kind="area"):
        if img.isNull():
            return
        ext = settings["format"]
        has_alpha = img.hasAlphaChannel() and any(img.pixelColor(x, y).alpha() < 255
                                                  for x, y in ((0, 0), (img.width() - 1, 0), (0, img.height() - 1)))
        path = self._new_path("png" if (ext != "jpg" or has_alpha) else "jpg")
        img.save(str(path), None, settings["jpg_quality"] if path.suffix == ".jpg" else -1)
        try:
            histstore.add(img, kind, path)
        except Exception:
            pass
        ac = settings["after_capture"]
        if ac["copy"]:
            QApplication.clipboard().setImage(img)
        if settings["play_sound"]:
            from .paths import res
            pop = res("pop.mp3")
            if not (os.path.exists(pop) and winutil.play_sound_file(pop)):
                try:
                    import winsound
                    winsound.MessageBeep(winsound.MB_OK)
                except Exception:
                    pass
        if ac["open_editor"]:
            self.open_editor(img, str(path))
        elif ac["quick_access"]:
            self.qa.add(img, str(path), "image", buddy=True)

    def restore_overlay(self):
        if not self.qa.restore_last():
            self.tray.showMessage("BBong Capture", "복원할 오버레이가 없습니다.", QSystemTrayIcon.Information, 2000)

    def _qa_action(self, name, card):
        path = card.path
        if card.kind == "image":
            img = QImage(path)
            if name == "copy":
                QApplication.clipboard().setImage(img)
                card.close_card()
            elif name == "edit":
                self.open_editor(img, path)
                card.close_card()
            elif name == "pin":
                self.pin_image(img)
                card.close_card()
            elif name == "save_as":
                from PyQt5.QtWidgets import QFileDialog
                dst, _ = QFileDialog.getSaveFileName(None, "다른 이름으로 저장", os.path.basename(path), "PNG (*.png);;JPEG (*.jpg)")
                if dst:
                    img.save(dst)
                    card.close_card()
            elif name == "folder":
                os.startfile(os.path.dirname(path))
            elif name == "copy_path":
                QApplication.clipboard().setText(path)
            elif name == "delete":
                from .history import _recycle
                _recycle(path)
                card.close_card()
        else:
            if name == "copy":
                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(path)])
                QApplication.clipboard().setMimeData(mime)
                card.close_card()
            elif name == "open":
                os.startfile(path)
            elif name == "folder":
                os.startfile(os.path.dirname(path))
            elif name == "delete":
                from .history import _recycle
                _recycle(path)
                card.close_card()

    # ------------------------------------------------------------------ editor / pin / history
    def open_editor(self, img, path=None):
        if path and str(path).lower().endswith(".bbcap"):
            ed = EditorWindow.open_project(path)
        else:
            ed = EditorWindow(img, path, settings)
        ed.pin_requested.connect(self.pin_image)
        ed.closed.connect(lambda w: self.editors.remove(w) if w in self.editors else None)
        self.editors.append(ed)
        ed.show()
        winutil.bring_to_front(ed)

    def pin_image(self, img, at=None):
        scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        w = PinWindow(img)
        w.move(at or QPoint(g.center().x() - w.width() // 2, g.center().y() - w.height() // 2))
        w.closed.connect(lambda x: self.pins.remove(x) if x in self.pins else None)
        w.edit_requested.connect(lambda im: self.open_editor(im, None))
        self.pins.append(w)
        w.show()

    def toggle_pin_lock(self):
        if not self.pins:
            return
        lock = not any(p.locked for p in self.pins)
        for p in self.pins:
            p.set_locked(lock)
        self.tray.showMessage("BBong Capture", "고정 화면을 잠갔습니다 (클릭 통과)" if lock else "고정 화면 잠금을 해제했습니다",
                              QSystemTrayIcon.Information, 1800)

    def pin_clipboard(self):
        img = QApplication.clipboard().image()
        if img.isNull():
            self.tray.showMessage("BBong Capture", "클립보드에 이미지가 없습니다.", QSystemTrayIcon.Information)
        else:
            self.pin_image(img)

    def edit_clipboard(self):
        img = QApplication.clipboard().image()
        if img.isNull():
            self.tray.showMessage("BBong Capture", "클립보드에 이미지가 없습니다.", QSystemTrayIcon.Information)
        else:
            self.open_editor(img, None)

    def show_history(self):
        if self.history is None:
            self.history = HistoryWindow()
            self.history.open_image.connect(lambda p: self.open_editor(QImage(p), p))
            self.history.pin_image.connect(lambda p: self.pin_image(QImage(p)))
            self.history.restore.connect(lambda p: self.qa.add(QImage(p), p, "image"))
        self.history.show()
        winutil.bring_to_front(self.history)
        self.history.reload()

    def show_prefs(self):
        if self.prefs is None:
            self.prefs = PrefsDialog()
            self.prefs.applied.connect(self.register_hotkeys)
            self.prefs.finished.connect(lambda _: setattr(self, "prefs", None))
        self.prefs.show()
        winutil.bring_to_front(self.prefs)

    # ------------------------------------------------------------------ OCR
    def capture_text(self):
        def cb(rect, shot, origin):
            img = shot.copy(rect.translated(-origin))
            self.tray.showMessage("BBong Capture", "텍스트를 인식하는 중…", QSystemTrayIcon.NoIcon, 1500)
            QApplication.processEvents()
            try:
                text = ocr.recognize(img)
            except Exception as e:
                self.tray.showMessage("BBong Capture", f"OCR 실패: {e}", QSystemTrayIcon.Warning)
                return
            if text:
                QApplication.clipboard().setText(text)
                preview = text if len(text) < 120 else text[:117] + "…"
                self.tray.showMessage("텍스트가 클립보드에 복사되었습니다", preview, QSystemTrayIcon.Information, 4000)
            else:
                self.tray.showMessage("BBong Capture", "선택 영역에서 텍스트를 찾지 못했습니다.", QSystemTrayIcon.Information)

        self._pick("area", cb)

    # ------------------------------------------------------------------ scrolling capture
    def capture_scrolling(self):
        if self.scroller is not None:
            self.scroller.stop()
            return

        def cb(rect, shot, origin):
            self.scroller = ScrollCapture(rect)
            self.scroller.result.connect(self._scroll_done)
            bar = AllInOneLikeBar("스크롤 캡처 중… 끝나면 완료를 누르세요", rect)
            bar.done.connect(lambda: self.scroller and self.scroller.stop())
            self.scroll_bar = bar
            bar.show()
            self.scroll_preview = ScrollPreview(rect)
            self.scroller.preview.connect(self.scroll_preview.update_image)
            self.scroll_preview.show()
            self.scroller.start()

        self._pick("area", cb)

    def _scroll_done(self, img):
        if self.scroll_bar:
            self.scroll_bar.close()
            self.scroll_bar = None
        if getattr(self, "scroll_preview", None):
            self.scroll_preview.close()
            self.scroll_preview = None
        self.scroller = None
        if img is None or img.isNull():
            self.tray.showMessage("BBong Capture", "스크롤 캡처에 실패했습니다.", QSystemTrayIcon.Warning)
            return
        self.handle_image(img, "scrolling")

    # ------------------------------------------------------------------ recording
    def toggle_recording(self, gif):
        if self.recorder is not None:
            self.stop_recording()
            return

        def cb(rect, shot, origin):
            n = settings["record"]["countdown"]
            if n > 0:
                self.countdown = CountdownWidget(n, rect.center())
                self.countdown.finished.connect(lambda: self.start_recording(rect, gif))
                self.countdown.go()
            else:
                self.start_recording(rect, gif)

        self._pick("area", cb)

    def start_recording(self, rect, gif):
        rc = settings["record"]
        ext = "gif" if gif else "mp4"
        name = datetime.now().strftime("BBongCapture %Y-%m-%d at %H.%M.%S")
        path = settings.save_dir() / f"{name}.{ext}"
        if settings["hide_desktop_icons"] and winutil.desktop_icons_visible():   # keep the desktop clean while recording
            winutil.set_desktop_icons(False)
            self._rec_hid_icons = True
            QApplication.processEvents()
            time.sleep(0.25)
        self.recorder = Recorder(rect, str(path), gif, rc["gif_fps"] if gif else rc["fps"], rc["show_cursor"], rc["show_clicks"])
        self.recorder.finished_file.connect(self._recording_done)
        frame = RegionFrame(self.recorder.rect)
        bar = RecordBar(self.recorder, self.recorder.rect)
        bar.stop_clicked.connect(self.stop_recording)
        bar.cancel_clicked.connect(self.cancel_recording)
        self.record_ui = [frame, bar]
        frame.show()
        bar.show()
        self.recorder.start()

    def stop_recording(self):
        if self.recorder:
            self.recorder.stop()
            self.tray.showMessage("BBong Capture", "녹화를 저장하는 중…", QSystemTrayIcon.NoIcon, 1500)

    def cancel_recording(self):
        if self.recorder:
            self.recorder.cancel()

    def _restore_rec_icons(self):
        if getattr(self, "_rec_hid_icons", False):
            self._rec_hid_icons = False
            try:
                winutil.set_desktop_icons(True)
            except Exception:
                pass

    def _recording_done(self, path, ok):
        self._restore_rec_icons()
        for w in self.record_ui:
            w.close()
        self.record_ui = []
        self.recorder = None
        if not ok:
            return
        thumb = video_thumb(path)
        if settings["after_capture"]["quick_access"]:
            self.qa.add(thumb, path, "video", buddy=True)
        else:
            self.tray.showMessage("녹화가 저장되었습니다", path, QSystemTrayIcon.Information)
        if settings["after_capture"]["copy"]:
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(path)])
            QApplication.clipboard().setMimeData(mime)

    def quit(self):
        self.hotkeys.unregister_all()
        if self.recorder:
            self.recorder.cancel()
            self.recorder.wait(2000)
        self._restore_rec_icons()
        self.tray.hide()
        self.app.quit()


class AllInOneLikeBar(QWidget):
    done = pyqtSignal()

    def __init__(self, text, rect):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(px(14), px(8), px(10), px(8))
        from PyQt5.QtWidgets import QLabel
        lay.addWidget(QLabel(text))
        b = QPushButton("완료")
        b.setObjectName("primary")
        b.clicked.connect(self.done)
        lay.addWidget(b)
        self.adjustSize()
        scr = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
        g = scr.geometry()
        y = rect.top() - self.height() - px(10)
        if y < g.top():
            y = min(rect.bottom() + px(10), g.bottom() - self.height() - px(10))
        self.move(max(g.left(), min(rect.center().x() - self.width() // 2, g.right() - self.width())), y)

    def paintEvent(self, _):
        paint_pill(self, px(16))

    def show(self):
        super().show()
        winutil.exclude_from_capture(self)


class ScrollPreview(QWidget):
    """Small glass overlay beside the capture region that shows the stitched result so far."""
    W = 170
    H = 300

    def __init__(self, rect):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._pm = None
        self._n = 0
        self._size = (0, 0)
        self.resize(px(self.W), px(self.H))
        scr = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
        g = scr.geometry()
        gap = px(14)
        if rect.right() + gap + self.width() <= g.right():
            x = rect.right() + gap
        elif rect.left() - gap - self.width() >= g.left():
            x = rect.left() - gap - self.width()
        else:
            x = g.right() - self.width() - gap
        y = max(g.top() + gap, min(rect.top(), g.bottom() - self.height() - gap))
        self.move(x, y)

    def update_image(self, img, n):
        self._pm = QPixmap.fromImage(img)
        self._n = n
        self._size = (img.width(), img.height())
        self.update()

    def paintEvent(self, _):
        paint_glass(self, px(18), 225, C["mode"] == "dark")
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        pad = px(10)
        top = px(30)
        area = QRectF(pad, top, self.width() - 2 * pad, self.height() - top - pad)
        p.setPen(QColor(C["text"]))
        p.drawText(QRectF(pad, px(6), self.width() - 2 * pad, px(22)), Qt.AlignVCenter | Qt.AlignLeft,
                   f"스크롤 미리보기 · {self._n}장")
        path = QPainterPath()
        path.addRoundedRect(area, px(10), px(10))
        p.fillPath(path, QColor(0, 0, 0, 70))
        if self._pm is not None and not self._pm.isNull():
            p.setClipPath(path)
            sc = min(area.width() / self._pm.width(), 1e9)
            w = self._pm.width() * sc
            h = self._pm.height() * sc
            if h > area.height():           # tall result: show the newest part (bottom), scaled to fit width
                src_h = area.height() / sc
                src = QRectF(0, self._pm.height() - src_h, self._pm.width(), src_h)
                p.drawPixmap(area, self._pm, src)
            else:
                p.drawPixmap(QRectF(area.left(), area.top(), w, h), self._pm, QRectF(self._pm.rect()))

    def show(self):
        super().show()
        winutil.exclude_from_capture(self)
