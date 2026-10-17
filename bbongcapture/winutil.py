"""Windows helpers: DPI, screen grabbing, window enumeration, misc Win32 tricks."""
import ctypes
import sys
from ctypes import wintypes

import mss
from PyQt5.QtCore import QPoint, QRect
from PyQt5.QtGui import QImage

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi


def enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def exclude_from_capture(widget):
    """Hide a window from screen capture (Windows 10 2004+)."""
    try:
        user32.SetWindowDisplayAffinity(int(widget.winId()), 0x11)
    except Exception:
        pass


def enable_acrylic(widget, dark=True) -> bool:
    """Acrylic blur-behind via SetWindowCompositionAttribute (Windows 10 1803+ / 11)."""
    class ACCENT(ctypes.Structure):
        _fields_ = [("state", ctypes.c_int), ("flags", ctypes.c_int), ("color", ctypes.c_uint), ("anim", ctypes.c_int)]

    class WCA(ctypes.Structure):
        _fields_ = [("attr", ctypes.c_int), ("data", ctypes.c_void_p), ("size", ctypes.c_size_t)]
    try:
        v = ctypes.c_int(1 if dark else 0)   # dark / light native title bar
        dwmapi.DwmSetWindowAttribute(int(widget.winId()), 20, ctypes.byref(v), 4)
        if dark:   # keep the dark bar but make the title text readable (Windows 11)
            for attr, col in ((35, 0x00221A1A), (36, 0x00FFFFFF)):   # caption / text colour (COLORREF)
                c = ctypes.c_uint(col)
                dwmapi.DwmSetWindowAttribute(int(widget.winId()), attr, ctypes.byref(c), 4)
    except Exception:
        pass
    try:
        tint = 0x661A1A22 if dark else 0x66F4F4F8   # AABBGGRR
        acc = ACCENT(4, 2, tint, 0)  # ACCENT_ENABLE_ACRYLICBLURBEHIND
        data = WCA(19, ctypes.cast(ctypes.pointer(acc), ctypes.c_void_p), ctypes.sizeof(acc))
        fn = user32.SetWindowCompositionAttribute
        fn.argtypes = [wintypes.HWND, ctypes.POINTER(WCA)]
        return bool(fn(int(widget.winId()), ctypes.byref(data)))
    except Exception:
        return False


def force_foreground(widget):
    """Make sure an overlay window really receives keyboard focus."""
    try:
        user32.keybd_event(0x12, 0, 0, 0)  # ALT down/up unlocks SetForegroundWindow
        user32.keybd_event(0x12, 0, 2, 0)
        user32.SetForegroundWindow(int(widget.winId()))
    except Exception:
        pass
    widget.activateWindow()
    widget.raise_()
    widget.setFocus()


def bring_to_front(widget):
    """Show a normal window and force it above everything, even when another app owns the foreground."""
    try:
        hwnd = int(widget.winId())
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)   # HWND_TOPMOST, NOSIZE|NOMOVE|SHOWWINDOW
        user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)   # HWND_NOTOPMOST (stays on top of others)
        force_foreground(widget)
    except Exception:
        widget.raise_()
        widget.activateWindow()


def monitors():
    """List of QRects for each physical monitor, in virtual-screen coordinates."""
    with mss.mss() as sct:
        return [QRect(m["left"], m["top"], m["width"], m["height"]) for m in sct.monitors[1:]]


def virtual_rect() -> QRect:
    with mss.mss() as sct:
        m = sct.monitors[0]
        return QRect(m["left"], m["top"], m["width"], m["height"])


def grab_rect(rect: QRect) -> QImage:
    with mss.mss() as sct:
        shot = sct.grab({"left": rect.x(), "top": rect.y(), "width": rect.width(), "height": rect.height()})
        return QImage(shot.bgra, shot.width, shot.height, shot.width * 4, QImage.Format_RGB32).copy()


def grab_virtual():
    """Returns (QImage of the whole virtual desktop, origin QPoint)."""
    r = virtual_rect()
    return grab_rect(r), QPoint(r.x(), r.y())


def cursor_pos():
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def button_down(vk=0x01) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def mouse_wheel(delta):
    user32.mouse_event(0x0800, 0, 0, ctypes.c_uint(delta & 0xFFFFFFFF).value, 0)


def mouse_hwheel(delta):
    user32.mouse_event(0x1000, 0, 0, ctypes.c_uint(delta & 0xFFFFFFFF).value, 0)  # MOUSEEVENTF_HWHEEL


def set_cursor_pos(x, y):
    user32.SetCursorPos(int(x), int(y))


_SKIP_TITLES = {"Program Manager", "Windows Input Experience", "Microsoft Text Input Application", "Settings "}


def list_windows(exclude=()):
    """Visible top-level windows, top of z-order first: (hwnd, title, QRect)."""
    out = []
    exclude = set(exclude)

    def cb(hwnd, _):
        if hwnd in exclude or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        cloaked = ctypes.c_int(0)
        dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4)
        if cloaked.value:
            return True
        ex = user32.GetWindowLongW(hwnd, -20)
        if ex & 0x80 and not ex & 0x40000:  # WS_EX_TOOLWINDOW without APPWINDOW
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if buf.value in _SKIP_TITLES:
            return True
        rc = wintypes.RECT()
        if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rc), ctypes.sizeof(rc)) != 0:
            user32.GetWindowRect(hwnd, ctypes.byref(rc))
        w, h = rc.right - rc.left, rc.bottom - rc.top
        if w < 2 or h < 2:
            return True
        out.append((hwnd, buf.value, QRect(rc.left, rc.top, w, h)))
        return True

    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(cb)
    user32.EnumWindows(proc, 0)
    return out


def _find_desktop_listview():
    progman = user32.FindWindowW("Progman", None)
    defview = user32.FindWindowExW(progman, 0, "SHELLDLL_DefView", None)
    if not defview:
        found = []

        def cb(hwnd, _):
            dv = user32.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None)
            if dv:
                found.append(dv)
                return False
            return True

        proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(cb)
        user32.EnumWindows(proc, 0)
        defview = found[0] if found else 0
    if not defview:
        return 0, 0
    return defview, user32.FindWindowExW(defview, 0, "SysListView32", None)


def desktop_icons_visible() -> bool:
    _, lv = _find_desktop_listview()
    return bool(lv and user32.IsWindowVisible(lv))


def set_desktop_icons(visible: bool):
    defview, lv = _find_desktop_listview()
    if defview and lv and desktop_icons_visible() != visible:
        user32.SendMessageW(defview, 0x0111, 0x7402, 0)  # WM_COMMAND, toggle desktop icons


APP_ID = "BBong Capture"


def setup_app_identity(display_name="BBong Capture", icon_path=None):
    """Give the process its own identity so Windows notifications say 'BBong Capture' instead of 'Python'."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    try:
        import winreg
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\AppUserModelId" + "\\" + APP_ID)
        try:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, display_name)
            if icon_path:
                winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(icon_path))
        finally:
            winreg.CloseKey(key)
    except OSError:
        pass


def set_autostart(enabled: bool):
    import os
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
    try:
        if enabled:
            exe = sys.executable
            if getattr(sys, "frozen", False):        # installed build: the exe itself is the app
                cmd = f'"{exe}"'
            else:
                if exe.lower().endswith("python.exe"):
                    exe = exe[:-10] + "pythonw.exe"
                script = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "main.py"))
                cmd = f'"{exe}" "{script}"'
            winreg.SetValueEx(key, "BBongCapture", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, "BBongCapture")
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


_snd_n = 0


def play_sound_file(path) -> bool:
    """Play an mp3/wav asynchronously through MCI (no extra dependencies)."""
    global _snd_n
    try:
        _snd_n += 1
        alias = f"bbsnd{_snd_n}"
        mci = ctypes.windll.winmm.mciSendStringW
        if mci(f'open "{path}" type mpegvideo alias {alias}', None, 0, None):
            return False
        mci(f"play {alias}", None, 0, None)
        if _snd_n > 1:
            mci(f"close bbsnd{_snd_n - 1}", None, 0, None)   # previous one has long finished
        return True
    except Exception:
        return False
