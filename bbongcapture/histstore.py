"""Capture history store: 30-day (configurable) archive, independent of the user's save folder."""
import json
import os
import shutil
import time
import uuid
from pathlib import Path

from .settings import data_dir, settings

KINDS = {"area": "영역", "window": "창", "fullscreen": "전체 화면", "scrolling": "스크롤", "other": "기타"}


def folder() -> Path:
    p = data_dir() / "history"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _meta_path() -> Path:
    return folder() / "index.json"


def load():
    try:
        with open(_meta_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(entries):
    try:
        with open(_meta_path(), "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False)
    except Exception:
        pass


def add(img, kind="area", source_path=None):
    """Store a copy of a capture. Returns the entry dict."""
    eid = uuid.uuid4().hex[:12]
    path = folder() / f"{eid}.png"
    img.save(str(path), "PNG")
    entry = {"id": eid, "file": path.name, "kind": kind, "time": time.time(), "w": img.width(), "h": img.height(),
             "source": str(source_path) if source_path else ""}
    entries = load()
    entries.append(entry)
    _save(entries)
    return entry


def prune(days=None):
    """Drop entries older than `days` (history archive only; the user's saved files are never touched)."""
    days = days or settings["history_days"]
    cutoff = time.time() - days * 86400
    keep, drop = [], []
    for e in load():
        (keep if e["time"] >= cutoff and (folder() / e["file"]).exists() else drop).append(e)
    for e in drop:
        try:
            (folder() / e["file"]).unlink()
        except OSError:
            pass
    if drop:
        _save(keep)
    return len(drop)


def remove(entry_id):
    keep = []
    for e in load():
        if e["id"] == entry_id:
            try:
                (folder() / e["file"]).unlink()
            except OSError:
                pass
        else:
            keep.append(e)
    _save(keep)


def clear():
    shutil.rmtree(folder(), ignore_errors=True)
    folder()


def path_of(entry):
    return folder() / entry["file"]
