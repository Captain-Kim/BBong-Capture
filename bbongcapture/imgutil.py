"""QImage <-> numpy helpers."""
import base64

import numpy as np
from PyQt5.QtCore import QBuffer, QByteArray, QIODevice
from PyQt5.QtGui import QImage


def to_rgb(img: QImage):
    """QImage -> HxWx3 uint8 RGB array (copy)."""
    q = img.convertToFormat(QImage.Format_RGB888)
    w, h = q.width(), q.height()
    arr = np.frombuffer(q.constBits().asstring(q.bytesPerLine() * h), np.uint8).reshape(h, q.bytesPerLine())
    return arr[:, :w * 3].reshape(h, w, 3).copy()


def from_rgb(arr) -> QImage:
    arr = np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    return QImage(arr.data, w, h, w * 3, QImage.Format_RGB888).copy()


def from_rgba_premul(arr) -> QImage:
    arr = np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    return QImage(arr.data, w, h, w * 4, QImage.Format_ARGB32_Premultiplied).copy()


def to_b64(img: QImage) -> str:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return base64.b64encode(bytes(ba)).decode("ascii")


def from_b64(s: str) -> QImage:
    img = QImage()
    img.loadFromData(base64.b64decode(s), "PNG")
    return img


def content_margins(img: QImage, tol=14):
    """Pixels of uniform border colour on each side: (left, right, top, bottom)."""
    a = to_rgb(img).astype(np.int16)
    if a.size == 0:
        return 0, 0, 0, 0
    bg = a[0, 0]
    diff = (np.abs(a - bg).max(axis=2) > tol)
    rows = np.where(diff.any(axis=1))[0]
    cols = np.where(diff.any(axis=0))[0]
    if rows.size == 0 or cols.size == 0:
        return 0, 0, 0, 0
    h, w = diff.shape
    return int(cols[0]), int(w - 1 - cols[-1]), int(rows[0]), int(h - 1 - rows[-1])
