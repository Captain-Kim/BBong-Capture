"""Where the bundled files (icon, fonts, sounds, photos) live: the project folder, or the PyInstaller bundle."""
import os
import sys


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def root() -> str:
    if frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def res(name: str) -> str:
    return os.path.join(root(), name)
