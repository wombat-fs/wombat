"""PyInstaller runtime hook: point python-mpv at the bundled libmpv.

Runs before any app code in a frozen build. python-mpv loads libmpv through
ctypes at import time and honours the ``MPV_DYLIB_PATH`` environment variable,
so we set it to the library we bundled with the app. This lets Wombat ship a
self-contained player instead of depending on a system libmpv being installed.

Does nothing when running from source (not frozen).
"""
import os
import sys

if getattr(sys, "frozen", False):
    _base = getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)
    for _name in (
        "libmpv.2.dylib", "libmpv.dylib",   # macOS
        "libmpv-2.dll", "mpv-2.dll",         # Windows
        "libmpv.so.2", "libmpv.so",          # Linux
    ):
        _cand = os.path.join(_base, _name)
        if os.path.exists(_cand):
            os.environ.setdefault("MPV_DYLIB_PATH", _cand)
            break
