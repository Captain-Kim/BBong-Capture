"""Scrolling capture: scrolls the window under the region and stitches the frames."""
import time

import cv2
import mss
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

from . import winutil


def find_shift(prev, cur):
    """How many pixels the content moved up between prev and cur. 0 = unchanged, None = unknown."""
    h = cur.shape[0]
    if np.mean(cv2.absdiff(prev, cur)) < 0.4:
        return 0
    if h < 90:
        return None
    th = min(70, h // 4)
    best = None
    # try several template rows so a sticky header/footer or a flat area does not break matching
    for a in (h // 4, h // 2 - th // 2, h // 8, 3 * h // 8):
        if a < 0 or a + th > h:
            continue
        tpl = cur[a:a + th]
        if tpl.std() < 3:
            continue
        res = cv2.matchTemplate(prev, tpl, cv2.TM_CCOEFF_NORMED)
        _, maxv, _, maxl = cv2.minMaxLoc(res)
        s = maxl[1] - a
        if maxv >= 0.85 and s > 0 and (best is None or maxv > best[0]):
            best = (maxv, s)
    return best[1] if best else None


def np_to_qimage(arr):
    arr = np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    return QImage(arr.data, w, h, w * 3, QImage.Format_BGR888).copy()


class ScrollCapture(QThread):
    progress = pyqtSignal(int)
    preview = pyqtSignal(object, int)  # QImage of the stitched result so far, frame count
    result = pyqtSignal(object)  # QImage or None

    def __init__(self, rect, max_steps=80):
        super().__init__()
        self.rect = rect
        self.max_steps = max_steps
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        r = self.rect
        region = {"left": r.x(), "top": r.y(), "width": r.width(), "height": r.height()}
        try:
            with mss.mss() as sct:
                horizontal = False

                def grab():
                    a = np.array(sct.grab(region))[:, :, :3].copy()
                    # horizontal scrolling reuses the vertical stitcher on the transposed image
                    return np.ascontiguousarray(a.transpose(1, 0, 2)) if horizontal else a

                def scroll():
                    if horizontal:
                        winutil.mouse_hwheel(120 * 3)
                    else:
                        winutil.mouse_wheel(-120 * 3)

                def settle(ref=None, limit=2.0):
                    """Wait until smooth scrolling has finished (two identical consecutive frames)."""
                    t0 = time.time()
                    last = grab()
                    while time.time() - t0 < limit:
                        time.sleep(0.12)
                        cur = grab()
                        if np.mean(cv2.absdiff(last, cur)) < 0.3:
                            return cur
                        last = cur
                    return last

                def emit_preview(parts):
                    try:
                        out = np.vstack(parts)
                        if horizontal:
                            out = out.transpose(1, 0, 2)
                        h, w = out.shape[:2]
                        k = min(1.0, 600.0 / max(h, w))
                        if k < 1.0:
                            out = cv2.resize(out, (max(1, int(w * k)), max(1, int(h * k))), interpolation=cv2.INTER_AREA)
                        self.preview.emit(np_to_qimage(out), len(parts))
                    except Exception:
                        pass

                winutil.set_cursor_pos(r.x() + r.width() // 2, r.y() + r.height() // 2)
                time.sleep(0.25)
                prev = settle()
                parts = [prev]
                emit_preview(parts)
                same = 0
                fails = 0
                for i in range(self.max_steps):
                    if self._stop:
                        break
                    scroll()
                    time.sleep(0.25)
                    cur = settle()
                    s = find_shift(prev, cur)
                    if s is None:
                        # transient (animation, lazy-loaded content): wait and retry before giving up
                        for _ in range(3):
                            time.sleep(0.5)
                            cur = settle()
                            s = find_shift(prev, cur)
                            if s is not None:
                                break
                    if s == 0:
                        same += 1
                        if same >= 2:
                            if len(parts) == 1 and not horizontal:    # nothing moved vertically: try sideways
                                horizontal = True
                                prev = settle()
                                parts = [prev]
                                same = 0
                                continue
                            break
                        continue
                    same = 0
                    if s is None:
                        fails += 1
                        if fails >= 2:
                            break
                        continue
                    fails = 0
                    parts.append(cur[cur.shape[0] - s:])
                    prev = cur
                    self.progress.emit(len(parts))
                    emit_preview(parts)
                out = np.vstack(parts)
                if horizontal:
                    out = np.ascontiguousarray(out.transpose(1, 0, 2))
                self.result.emit(np_to_qimage(out))
        except Exception:
            self.result.emit(None)
