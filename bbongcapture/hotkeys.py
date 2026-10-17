"""Global hotkeys through the native Win32 RegisterHotKey API (no keyboard hooks, no admin rights needed)."""
import ctypes
from ctypes import wintypes

from PyQt5.QtCore import QAbstractNativeEventFilter

user32 = ctypes.windll.user32
WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000

MODS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "shift": MOD_SHIFT, "alt": MOD_ALT,
        "win": MOD_WIN, "windows": MOD_WIN, "meta": MOD_WIN}
NAMED = {"space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
         "backspace": 0x08, "del": 0x2E, "delete": 0x2E, "ins": 0x2D, "insert": 0x2D, "home": 0x24, "end": 0x23,
         "pgup": 0x21, "page up": 0x21, "pgdown": 0x22, "page down": 0x22, "left": 0x25, "up": 0x26,
         "right": 0x27, "down": 0x28, "print": 0x2C, "print screen": 0x2C, "prtsc": 0x2C, "pause": 0x13,
         "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE,
         "/": 0xBF, "\\": 0xDC}


def parse(combo: str):
    """'ctrl+shift+4' -> (modifiers, virtual-key). Raises ValueError for unknown keys."""
    mods, vk = 0, None
    for part in [p.strip().lower() for p in combo.split("+") if p.strip()]:
        if part in MODS:
            mods |= MODS[part]
        elif part in NAMED:
            vk = NAMED[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            vk = 0x70 + int(part[1:]) - 1
        else:
            raise ValueError(f"알 수 없는 키: {part}")
    if vk is None:
        raise ValueError("일반 키가 없습니다")
    return mods, vk


class HotkeyManager(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback  # callback(name)
        self.ids = {}             # id -> name
        self._next = 1

    def unregister_all(self):
        for i in list(self.ids):
            user32.UnregisterHotKey(None, i)
        self.ids.clear()

    def register(self, name, combo):
        """Returns None on success or a human-readable error string."""
        try:
            mods, vk = parse(combo)
        except ValueError as e:
            return str(e)
        hid = self._next
        self._next += 1
        if not user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk):
            err = ctypes.get_last_error() or ctypes.windll.kernel32.GetLastError()
            return "다른 프로그램이 이미 사용 중인 단축키입니다" if err == 1409 else f"등록 실패 (오류 {err})"
        self.ids[hid] = name
        return None

    def nativeEventFilter(self, event_type, message):
        if event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            try:
                msg = wintypes.MSG.from_address(int(message))
            except Exception:
                return False, 0
            if msg.message == WM_HOTKEY and msg.wParam in self.ids:
                self.callback(self.ids[msg.wParam])
                return True, 0
        return False, 0
