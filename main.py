"""BBong Capture — entry point."""
import os
import sys

# Physical-pixel coordinates everywhere so overlay, mss and Win32 agree on multi-monitor / HiDPI setups.
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
os.environ["QT_SCALE_FACTOR"] = "1"

from bbongcapture import winutil  # noqa: E402

winutil.enable_dpi_awareness()

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon  # noqa: E402


def _excepthook(et, ev, tb):
    # PyQt5 aborts the process on unhandled exceptions inside slots; log instead.
    import traceback
    try:
        from bbongcapture.settings import data_dir
        with open(data_dir() / "error.log", "a", encoding="utf-8") as f:
            traceback.print_exception(et, ev, tb, file=f)
    except Exception:
        pass
    traceback.print_exception(et, ev, tb)


def main():
    sys.excepthook = _excepthook
    QApplication.setAttribute(Qt.AA_DisableHighDpiScaling, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("BBong Capture")

    from bbongcapture import fonts
    fonts.load_fonts()            # bundled Pretendard (before the theme, which uses it)
    from bbongcapture.theme import app_icon, apply_theme
    from bbongcapture.settings import settings
    apply_theme(app, settings["theme"])
    app.setWindowIcon(app_icon())

    # own app identity -> notifications show "BBong Capture" (with our icon) instead of "Python"
    try:
        from bbongcapture import winutil
        from bbongcapture.settings import data_dir
        icon_png = data_dir() / "icon.png"
        app_icon().pixmap(256, 256).save(str(icon_png), "PNG")
        winutil.setup_app_identity("BBong Capture", icon_png)
    except Exception:
        pass
    app.setApplicationDisplayName("BBong Capture")

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "BBong Capture", "시스템 트레이를 사용할 수 없습니다.")
        return 1

    # a newly started instance replaces an older one (otherwise both grab the same hotkeys)
    from bbongcapture.single import SingleServer, take_over
    try:
        from bbongcapture import winutil
        from bbongcapture.settings import settings
        if settings["start_with_windows"]:
            winutil.set_autostart(True)     # keeps the Run entry present and pointing at this install
    except Exception:
        pass
    take_over()

    from bbongcapture.app import Controller
    ctl = Controller(app)  # noqa: F841 (kept alive for the process lifetime)
    single = SingleServer(ctl.quit)  # noqa: F841
    ctl.tray.showMessage("BBong Capture 실행 중", "Ctrl+Shift+4로 영역을 캡처하거나 트레이 아이콘을 클릭하세요.",
                         QSystemTrayIcon.Information, 3500)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
