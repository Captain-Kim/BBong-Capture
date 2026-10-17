"""Preferences dialog."""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QKeySequenceEdit,
                             QLabel, QLineEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from .settings import HOTKEY_LABELS, settings
from .theme import C, px
from . import winutil


def _rounded_logo(size):
    """bbong.jpg / bbong.png from the project folder, cut to a rounded square."""
    import os
    from PyQt5.QtCore import QRectF
    from PyQt5.QtGui import QImage, QPainter, QPainterPath, QPixmap
    from .paths import root as _root
    root = _root()
    for name in ("bbong.png", "bbong.jpg", "bbong.jpeg"):
        from PyQt5.QtGui import QImageReader
        rd = QImageReader(os.path.join(root, name))
        rd.setAutoTransform(True)          # honour the EXIF rotation of phone photos
        img = rd.read()
        if img.isNull():
            continue
        side = min(img.width(), img.height())
        img = img.copy((img.width() - side) // 2, (img.height() - side) // 2, side, side)
        img = img.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        out = QPixmap(size, size)
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, size, size), size * 0.24, size * 0.24)
        p.setClipPath(path)
        p.drawImage(0, 0, img)
        p.end()
        return out
    return None


class PrefsDialog(QDialog):
    applied = pyqtSignal()

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_glassed", False):
            self._glassed = True
            from .theme import glassify
            glassify(self)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("환경설정")
        self.resize(px(560), px(520))
        s = settings.data
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs)

        # ---- General
        g = QWidget()
        f = QFormLayout(g)
        self.save_dir = QLineEdit(s["save_dir"])
        b = QPushButton("찾아보기…")
        b.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.save_dir)
        row.addWidget(b)
        f.addRow("저장 위치", row)
        self.fmt = QComboBox()
        self.fmt.addItems(["png", "jpg"])
        self.fmt.setCurrentText(s["format"])
        f.addRow("이미지 형식", self.fmt)
        self.c_qa = QCheckBox("퀵 액세스 미리보기 표시")
        self.c_qa.setChecked(s["after_capture"]["quick_access"])
        self.c_copy = QCheckBox("클립보드에 복사")
        self.c_copy.setChecked(s["after_capture"]["copy"])
        self.c_edit = QCheckBox("편집기 열기")
        self.c_edit.setChecked(s["after_capture"]["open_editor"])
        f.addRow("캡처 후", self.c_qa)
        f.addRow("", self.c_copy)
        f.addRow("", self.c_edit)
        self.c_autosave = QCheckBox("캡처할 때마다 저장 위치에 자동 저장")
        self.c_autosave.setChecked(s["after_capture"].get("auto_save", False))
        f.addRow("", self.c_autosave)
        self.qa_sec = QSpinBox()
        self.qa_sec.setRange(0, 60)
        self.qa_sec.setSuffix(" 초  (0 = 유지)")
        self.qa_sec.setValue(s["quick_access_seconds"])
        f.addRow("퀵 액세스 자동 닫힘", self.qa_sec)
        self.qa_side = QComboBox()
        for key, label in (("bottom-left", "왼쪽 아래"), ("bottom-right", "오른쪽 아래"),
                           ("top-left", "왼쪽 위"), ("top-right", "오른쪽 위")):
            self.qa_side.addItem(label, key)
        self.qa_side.setCurrentIndex(max(0, self.qa_side.findData(s["quick_access_pos"])))
        f.addRow("퀵 액세스 위치", self.qa_side)
        self.c_icons = QCheckBox("캡처 중 바탕화면 아이콘 숨기기")
        self.c_icons.setChecked(s["hide_desktop_icons"])
        f.addRow("바탕화면", self.c_icons)
        self.c_sound = QCheckBox("캡처 후 소리 재생")
        self.c_sound.setChecked(s["play_sound"])
        f.addRow("소리", self.c_sound)
        self.c_start = QCheckBox("Windows 로그인 시 BBong Capture 자동 실행")
        self.c_start.setChecked(s["start_with_windows"])
        f.addRow("시작", self.c_start)
        tabs.addTab(g, "일반")

        # ---- Shortcuts
        sc = QWidget()
        sf = QFormLayout(sc)
        self.keys = {}
        for k, label in HOTKEY_LABELS.items():
            e = QKeySequenceEdit(QKeySequence(s["hotkeys"].get(k, "")))
            self.keys[k] = e
            sf.addRow(label, e)
        sf.addRow(QLabel("팁: 칸을 비우면 해당 단축키가 해제됩니다."))
        tabs.addTab(sc, "단축키")

        # ---- Recording
        rc = QWidget()
        rf = QFormLayout(rc)
        r = s["record"]
        self.fps = QSpinBox()
        self.fps.setRange(5, 60)
        self.fps.setValue(r["fps"])
        rf.addRow("영상 FPS", self.fps)
        self.gfps = QSpinBox()
        self.gfps.setRange(4, 30)
        self.gfps.setValue(r["gif_fps"])
        rf.addRow("GIF FPS", self.gfps)
        self.cd = QSpinBox()
        self.cd.setRange(0, 10)
        self.cd.setValue(r["countdown"])
        rf.addRow("카운트다운 (초)", self.cd)
        self.c_cursor = QCheckBox("마우스 커서 표시")
        self.c_cursor.setChecked(r["show_cursor"])
        self.c_clicks = QCheckBox("마우스 클릭 강조")
        self.c_clicks.setChecked(r["show_clicks"])
        rf.addRow("", self.c_cursor)
        rf.addRow("", self.c_clicks)
        tabs.addTab(rc, "녹화")

        # ---- About
        ab = QWidget()
        al = QVBoxLayout(ab)
        head = QHBoxLayout()
        pic = _rounded_logo(px(96))
        if pic is not None:
            lbl = QLabel()
            lbl.setPixmap(pic)
            lbl.setFixedSize(pic.size())
            head.addWidget(lbl, 0, Qt.AlignTop)
        head.addWidget(QLabel("<h2>BBong Capture</h2>Windows용 스크린샷 · 화면 녹화 도구입니다."), 1, Qt.AlignVCenter)
        al.addLayout(head)
        al.addWidget(QLabel("영역 / 창 / 전체 화면 / 스크롤 캡처, OCR, GIF · MP4 녹화, "
                            "주석 편집기, 퀵 액세스, 화면 고정, 캡처 기록을 지원합니다."))
        story = QLabel("뽕캡처는 우리 집 강아지 짬뽕이가 만든 캡처 프로그램입니다.")
        story.setWordWrap(True)
        al.addWidget(story)
        guide = QLabel('사용법은 <a href="https://github.com/Captain-Kim/BBong-Capture" '
                       f'style="color:{C["accent"]}">여기</a>에서 보실 수 있습니다.')
        guide.setOpenExternalLinks(True)
        guide.setTextInteractionFlags(Qt.TextBrowserInteraction)
        guide.setCursor(Qt.PointingHandCursor)
        al.addWidget(guide)
        al.addStretch()
        tabs.addTab(ab, "정보")

        bb = QHBoxLayout()
        bb.addStretch()
        ok = QPushButton("저장")
        ok.setObjectName("primary")
        ok.clicked.connect(self._save)
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        bb.addWidget(cancel)
        bb.addWidget(ok)
        lay.addLayout(bb)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "저장 위치", self.save_dir.text())
        if d:
            self.save_dir.setText(d)

    def _save(self):
        s = settings.data
        s["save_dir"] = self.save_dir.text() or s["save_dir"]
        s["format"] = self.fmt.currentText()
        s["after_capture"] = {"quick_access": self.c_qa.isChecked(), "copy": self.c_copy.isChecked(),
                              "open_editor": self.c_edit.isChecked(),
                              "auto_save": self.c_autosave.isChecked()}
        s["quick_access_seconds"] = self.qa_sec.value()
        s["quick_access_pos"] = self.qa_side.currentData()
        s["hide_desktop_icons"] = self.c_icons.isChecked()
        s["play_sound"] = self.c_sound.isChecked()
        if s["start_with_windows"] != self.c_start.isChecked():
            try:
                winutil.set_autostart(self.c_start.isChecked())
            except Exception:
                pass
        s["start_with_windows"] = self.c_start.isChecked()
        for k, e in self.keys.items():
            seq = e.keySequence().toString().split(",")[0].strip().lower().replace("meta", "windows")
            s["hotkeys"][k] = seq
        s["record"].update(fps=self.fps.value(), gif_fps=self.gfps.value(), countdown=self.cd.value(),
                           show_cursor=self.c_cursor.isChecked(), show_clicks=self.c_clicks.isChecked())
        settings.save()
        self.applied.emit()
        self.accept()
