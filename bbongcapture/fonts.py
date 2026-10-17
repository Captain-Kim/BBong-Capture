"""Bundled fonts (Pretendard) and the app-wide default family."""
import os
from pathlib import Path

from PyQt5.QtGui import QFont, QFontDatabase

from .paths import root as _root

ROOT = Path(_root())
_family = "Segoe UI"
_loaded = []


def load_fonts():
    """Register every .ttf/.otf found in the project root or ./fonts. Returns the default family name."""
    global _family
    QFontDatabase()  # make sure the database exists
    for folder in (ROOT / "fonts", ROOT):
        if not folder.is_dir():
            continue
        for f in sorted(folder.iterdir()):
            if f.suffix.lower() in (".ttf", ".otf") and f.name not in _loaded:
                fid = QFontDatabase.addApplicationFont(str(f))
                if fid >= 0:
                    _loaded.append(f.name)
                    fams = QFontDatabase.applicationFontFamilies(fid)
                    if fams and "pretendard" in fams[0].lower():
                        _family = fams[0]
                    elif fams and _family == "Segoe UI":
                        _family = fams[0]
    return _family


def family() -> str:
    return _family


def make(px_size=None, pt=None, bold=False, fam=None) -> QFont:
    f = QFont(fam or _family)
    if px_size:
        f.setPixelSize(int(px_size))
    elif pt:
        f.setPointSizeF(pt)
    f.setBold(bold)
    return f


# families offered in the text tool; only those installed are shown
CANDIDATES = ["Pretendard Variable", "Pretendard", "맑은 고딕", "Segoe UI", "Arial", "Georgia", "Consolas",
              "Malgun Gothic", "바탕", "궁서", "Comic Sans MS"]


def text_families():
    db = QFontDatabase()
    have = set(db.families())
    out = [f for f in CANDIDATES if f in have]
    if _family not in out:
        out.insert(0, _family)
    seen, res = set(), []
    for f in out:
        k = f.lower()
        if k not in seen:
            seen.add(k)
            res.append(f)
    return res
