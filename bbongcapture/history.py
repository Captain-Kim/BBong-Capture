"""Capture History window: browse, filter, restore and delete recent captures."""
import os
import subprocess
from datetime import datetime

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QIcon, QImage, QPixmap
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                             QMessageBox, QMenu, QPushButton, QVBoxLayout, QWidget)

from . import histstore
from .theme import glassify, icon, px, round_menu

import cv2


def video_thumb(path: str):
    try:
        if path.lower().endswith(".gif"):
            from PIL import Image
            im = Image.open(path).convert("RGB")
            return QImage(im.tobytes(), im.width, im.height, im.width * 3, QImage.Format_RGB888).copy()
        cap = cv2.VideoCapture(path)
        ok, frame = cap.read()
        cap.release()
        if ok:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w = frame.shape[:2]
            return QImage(frame.data, w, h, w * 3, QImage.Format_RGB888).copy()
    except Exception:
        pass
    return QImage()


class HistoryWindow(QWidget):
    open_image = pyqtSignal(str)
    pin_image = pyqtSignal(str)
    restore = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("캡처 기록")
        self.resize(px(980), px(660))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(px(16), px(14), px(16), px(14))
        top = QHBoxLayout()
        self.filter = "all"
        self.fbtns = {}
        for key, text in [("all", "전체")] + [(k, v) for k, v in histstore.KINDS.items() if k != "other"]:
            b = QPushButton(text)
            b.setCheckable(True)
            b.clicked.connect(lambda _, k=key: self.set_filter(k))
            top.addWidget(b)
            self.fbtns[key] = b
        self.fbtns["all"].setChecked(True)
        top.addStretch()
        self.count = QLabel()
        self.count.setObjectName("muted")
        top.addWidget(self.count)
        clr = QPushButton("모두 삭제")
        clr.clicked.connect(self._clear_all)
        top.addWidget(clr)
        lay.addLayout(top)
        note = QLabel("최근 30일간의 캡처가 보관됩니다. 항목을 더블클릭하면 편집기에서 열립니다.")
        note.setObjectName("muted")
        lay.addWidget(note)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(px(210), px(136)))
        self.list.setGridSize(QSize(px(236), px(190)))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setSpacing(px(4))
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setWordWrap(True)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.itemDoubleClicked.connect(lambda it: self.open_image.emit(it.data(Qt.UserRole)))
        lay.addWidget(self.list)

    def set_filter(self, k):
        self.filter = k
        for kk, b in self.fbtns.items():
            b.setChecked(kk == k)
        self.reload()

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_glassed", False):
            self._glassed = True
            glassify(self)
        self.reload()

    def reload(self):
        self.list.clear()
        histstore.prune()
        entries = [e for e in histstore.load() if self.filter in ("all", e["kind"])]
        entries.sort(key=lambda e: e["time"], reverse=True)
        for e in entries[:500]:
            path = str(histstore.path_of(e))
            img = QImage(path)
            if img.isNull():
                continue
            pm = QPixmap.fromImage(img.scaled(self.list.iconSize(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            kind = histstore.KINDS.get(e["kind"], "기타")
            label = f"{kind} · {e['w']}×{e['h']}\n{datetime.fromtimestamp(e['time']):%m-%d %H:%M:%S}"
            it = QListWidgetItem(QIcon(pm), label)
            it.setData(Qt.UserRole, path)
            it.setData(Qt.UserRole + 1, e["id"])
            it.setTextAlignment(Qt.AlignHCenter)
            self.list.addItem(it)
        self.count.setText(f"{self.list.count()}개 항목   ")

    def _sel(self):
        return [(i.data(Qt.UserRole), i.data(Qt.UserRole + 1)) for i in self.list.selectedItems()]

    def _menu(self, pos):
        sel = self._sel()
        if not sel:
            return
        path = sel[0][0]
        m = round_menu(QMenu(self))
        m.addAction(icon("restore"), "퀵 액세스로 복원", lambda: self.restore.emit(path))
        m.addAction(icon("edit"), "편집기에서 열기", lambda: self.open_image.emit(path))
        m.addAction(icon("copy"), "이미지 복사", lambda: QApplication.clipboard().setImage(QImage(path)))
        m.addAction(icon("pin"), "화면에 고정", lambda: self.pin_image.emit(path))
        m.addAction(icon("folder"), "탐색기에서 보기", lambda: subprocess.Popen(["explorer", "/select,", os.path.normpath(path)]))
        m.addSeparator()
        m.addAction(icon("trash"), f"기록에서 삭제 ({len(sel)})", lambda: self._delete(sel))
        m.exec_(self.list.mapToGlobal(pos))

    def _delete(self, sel):
        for _, eid in sel:
            histstore.remove(eid)
        self.reload()

    def _clear_all(self):
        if QMessageBox.question(self, "모두 삭제", "캡처 기록을 모두 삭제할까요? (저장 폴더의 파일은 삭제되지 않습니다)") == QMessageBox.Yes:
            histstore.clear()
            self.reload()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Delete and self._sel():
            self._delete(self._sel())
        else:
            super().keyPressEvent(e)


def _recycle(path):
    """Send a file to the Recycle Bin via SHFileOperation."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCT(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    op = SHFILEOPSTRUCT()
    op.wFunc = 3  # FO_DELETE
    op.pFrom = os.path.abspath(path) + "\0"
    op.fFlags = 0x0040 | 0x0010 | 0x0004 | 0x0400  # ALLOWUNDO | NOCONFIRMATION | SILENT | NOERRORUI
    ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
