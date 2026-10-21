"""Persistent JSON settings."""
import copy
import json
import os
from pathlib import Path

APP_NAME = "BBong Capture"


def data_dir() -> Path:
    base = Path(os.environ.get("APPDATA", str(Path.home())))
    p = base / "BBongCapture"
    p.mkdir(parents=True, exist_ok=True)
    return p


DEFAULTS = {
    "save_dir": str(Path.home() / "Pictures" / "BBong Capture"),
    "format": "png",
    "jpg_quality": 92,
    "after_capture": {"quick_access": True, "copy": True, "open_editor": False, "auto_save": False},
    "quick_access_seconds": 7,
    "quick_access_pos": "bottom-left",
    "quick_access_size": "medium",
    "quick_access_info": True,
    "buddy_toast": True,
    "theme": "dark",
    "show_crosshair": True,
    "show_magnifier": True,
    "freeze_screen": True,
    "window_background": False,
    "window_round_corners": True,
    "window_shadow": True,
    "history_days": 30,
    "fav_colors": [],
    "bg_presets": {},
    "bg_last": None,
    "aio_ratio": "자유",
    "hide_desktop_icons": False,
    "play_sound": True,
    "start_with_windows": True,
    "last_area": None,
    "record": {
        "fps": 30,
        "gif_fps": 12,
        "show_cursor": True,
        "show_clicks": True,
        "countdown": 3,
    },
    "hotkeys": {
        "all_in_one": "ctrl+shift+1",
        "ocr": "ctrl+shift+2",
        "fullscreen": "ctrl+shift+3",
        "area": "ctrl+shift+4",
        "window": "ctrl+shift+5",
        "scrolling": "ctrl+shift+6",
        "record": "ctrl+shift+7",
        "record_gif": "ctrl+shift+8",
        "repeat_area": "ctrl+shift+9",
        "history": "ctrl+shift+h",
        "restore_overlay": "ctrl+shift+0",
        "toggle_overlays": "ctrl+shift+-",
        "pin_lock": "ctrl+shift+l",
    },
}

HOTKEY_LABELS = {
    "all_in_one": "올인원",
    "ocr": "텍스트 캡처 (OCR)",
    "fullscreen": "전체 화면 캡처",
    "area": "영역 캡처",
    "window": "창 캡처",
    "scrolling": "스크롤 캡처",
    "record": "화면 녹화 (MP4)",
    "record_gif": "GIF 녹화",
    "repeat_area": "이전 영역 다시 캡처",
    "history": "캡처 기록",
    "restore_overlay": "닫은 오버레이 복원",
    "toggle_overlays": "오버레이 숨기기/보이기",
    "pin_lock": "고정 화면 잠금/해제",
}


def _merge(base: dict, new: dict):
    for k, v in new.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v


class Settings:
    def __init__(self):
        self.path = data_dir() / "settings.json"
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                _merge(self.data, json.load(f))
        except Exception:
            pass

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v

    def temp_dir(self) -> Path:
        """Working folder for captures that are not auto-saved (cleaned up automatically)."""
        p = data_dir() / "temp"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def save_dir(self) -> Path:
        p = Path(self.data["save_dir"])
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
