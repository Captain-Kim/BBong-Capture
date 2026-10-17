"""Background tool: gradients / colours / images behind a screenshot, with padding, alignment, ratio, shadow."""
import copy
import ctypes
import math
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np
from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath

from . import imgutil

# 20 hand-picked backgrounds: (name, angle, [(stop, colour), ...])
GRADIENTS = [
    ("바다", 135, [(0, "#4facfe"), (1, "#00f2fe")]),
    ("노을", 135, [(0, "#ff9a9e"), (1, "#fecfef")]),
    ("포도", 135, [(0, "#667eea"), (1, "#764ba2")]),
    ("민트", 135, [(0, "#43e97b"), (1, "#38f9d7")]),
    ("불꽃", 135, [(0, "#f83600"), (1, "#f9d423")]),
    ("슬레이트", 135, [(0, "#485563"), (1, "#29323c")]),
    ("눈", 135, [(0, "#f5f7fa"), (1, "#c3cfe2")]),
    ("오로라", 160, [(0, "#00c6ff"), (0.5, "#7b4397"), (1, "#dc2430")]),
    ("체리", 135, [(0, "#eb3349"), (1, "#f45c43")]),
    ("라벤더", 135, [(0, "#a18cd1"), (1, "#fbc2eb")]),
    ("피치", 135, [(0, "#ffecd2"), (1, "#fcb69f")]),
    ("딥 스페이스", 150, [(0, "#000428"), (1, "#004e92")]),
    ("라임", 135, [(0, "#a8e063"), (1, "#56ab2f")]),
    ("사탕", 135, [(0, "#ff6a88"), (0.5, "#ff99ac"), (1, "#fcb69f")]),
    ("네온", 135, [(0, "#12c2e9"), (0.5, "#c471ed"), (1, "#f64f59")]),
    ("모래", 135, [(0, "#d4b483"), (1, "#f7e7ce")]),
    ("북극", 180, [(0, "#2193b0"), (1, "#6dd5ed")]),
    ("와인", 135, [(0, "#4b134f"), (1, "#c94b4b")]),
    ("미드나잇", 135, [(0, "#232526"), (1, "#414345")]),
    ("솜사탕", 135, [(0, "#74ebd5"), (1, "#acb6e5")]),
]

RATIOS = {"자동": None, "1:1": 1.0, "4:3": 4 / 3, "3:2": 3 / 2, "16:9": 16 / 9, "2:1": 2.0, "4:5": 4 / 5, "9:16": 9 / 16}


@dataclass
class BgSpec:
    kind: str = "none"          # none | transparent | gradient | solid | image | wallpaper
    gradient: int = 0
    color: str = "#4facfe"
    image: str = ""
    padding: int = 64
    align: tuple = (0.5, 0.5)
    ratio: str = "자동"
    radius: int = 12
    shadow: bool = True
    shadow_blur: int = 40
    shadow_opacity: int = 55
    balance: bool = False

    def to_dict(self):
        d = asdict(self)
        d["align"] = list(self.align)
        return d

    @staticmethod
    def from_dict(d):
        s = BgSpec()
        for k, v in (d or {}).items():
            if hasattr(s, k):
                setattr(s, k, tuple(v) if k == "align" else v)
        return s

    def active(self):
        return self.kind != "none"

    def clone(self):
        return copy.deepcopy(self)


def wallpaper_path():
    try:
        buf = ctypes.create_unicode_buffer(520)
        ctypes.windll.user32.SystemParametersInfoW(0x0073, 520, buf, 0)  # SPI_GETDESKWALLPAPER
        return buf.value
    except Exception:
        return ""


_img_cache = {}


def _load(path):
    if path not in _img_cache:
        _img_cache[path] = QImage(path)
    return _img_cache[path]


def layout(spec: BgSpec, w, h, margins=None):
    """Canvas rect, with the content occupying QRectF(0, 0, w, h)."""
    if not spec.active():
        return QRectF(0, 0, w, h)
    p = spec.padding
    W0, H0 = w + 2 * p, h + 2 * p
    ratio = RATIOS.get(spec.ratio)
    W, H = W0, H0
    if ratio:
        if W0 / H0 < ratio:
            W = H0 * ratio
        else:
            H = W0 / ratio
    ax, ay = spec.align
    left = p + (W - w - 2 * p) * ax
    top = p + (H - h - 2 * p) * ay
    if spec.balance and margins:
        ml, mr, mt, mb = margins
        left = max(0, left + (mr - ml) / 2)
        top = max(0, top + (mb - mt) / 2)
    return QRectF(-left, -top, W, H)


def paint_background(painter: QPainter, rect: QRectF, spec: BgSpec):
    if spec.kind == "gradient":
        _, angle, stops = GRADIENTS[spec.gradient % len(GRADIENTS)]
        a = math.radians(angle)
        dx, dy = math.sin(a), -math.cos(a)  # CSS-style: 0deg = up, 90deg = right
        half = (abs(rect.width() * dx) + abs(rect.height() * dy)) / 2
        c = rect.center()
        g = QLinearGradient(QPointF(c.x() - dx * half, c.y() - dy * half), QPointF(c.x() + dx * half, c.y() + dy * half))
        for pos, col in stops:
            g.setColorAt(pos, QColor(col))
        painter.fillRect(rect, g)
    elif spec.kind == "solid":
        painter.fillRect(rect, QColor(spec.color))
    elif spec.kind in ("image", "wallpaper"):
        path = spec.image if spec.kind == "image" else wallpaper_path()
        img = _load(path) if path else QImage()
        if img.isNull():
            painter.fillRect(rect, QColor("#2c2c30"))
            return
        scaled = img.scaled(rect.size().toSize(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        painter.save()
        painter.setClipRect(rect)
        painter.drawImage(QPointF(rect.center().x() - scaled.width() / 2, rect.center().y() - scaled.height() / 2), scaled)
        painter.restore()


def shadow_image(w, h, content: QRectF, blur, opacity, radius):
    """Premultiplied-ARGB shadow layer of canvas size w x h."""
    m = np.zeros((h, w), np.uint8)
    x0, y0 = max(0, int(content.left())), max(0, int(content.top() + blur / 4))
    x1, y1 = min(w, int(content.right())), min(h, int(content.bottom() + blur / 4))
    if x1 > x0 and y1 > y0:
        m[y0:y1, x0:x1] = 255
    sigma = max(1.0, blur / 2.4)
    m = cv2.GaussianBlur(m, (0, 0), sigma)
    a = (m.astype(np.float32) * (opacity / 100.0)).astype(np.uint8)
    arr = np.zeros((h, w, 4), np.uint8)
    arr[..., 3] = a
    return imgutil.from_rgba_premul(arr)


def round_corners(img: QImage, radius) -> QImage:
    if radius <= 0:
        return img
    out = QImage(img.size(), QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(out.rect()), radius, radius)
    p.setClipPath(path)
    p.drawImage(0, 0, img)
    p.end()
    return out


def compose(img: QImage, spec: BgSpec) -> QImage:
    """Flat render of img on its background (used for window captures and exports)."""
    if not spec.active():
        return img
    w, h = img.width(), img.height()
    margins = imgutil.content_margins(img) if spec.balance else None
    canvas = layout(spec, w, h, margins)
    W, H = int(round(canvas.width())), int(round(canvas.height()))
    out = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    p.translate(-canvas.left(), -canvas.top())
    if spec.kind != "transparent":
        paint_background(p, QRectF(canvas), spec)
    p.resetTransform()
    content = QRectF(-canvas.left(), -canvas.top(), w, h)
    if spec.shadow:
        p.drawImage(0, 0, shadow_image(W, H, content, spec.shadow_blur, spec.shadow_opacity, spec.radius))
    p.drawImage(content.topLeft(), round_corners(img, spec.radius))
    p.end()
    return out
