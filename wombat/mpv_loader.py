"""Pre-load libmpv on macOS where ctypes.util.find_library misses the Homebrew dylib.

python-mpv calls ctypes.util.find_library('mpv') at module import time. On macOS
with Homebrew, that call returns None because Homebrew's lib dir is not in the
default dyld search path for find_library. We patch find_library to return the
known path so the subsequent CDLL() load in python-mpv succeeds.
"""

import ctypes.util
import os
import sys

_original_find_library = ctypes.util.find_library


def _patched_find_library(name: str) -> str | None:
    result = _original_find_library(name)
    if result is not None or name != "mpv":
        return result

    candidates = []
    if env_path := os.environ.get("MPV_DYLIB_PATH"):
        candidates.append(env_path)
    candidates += [
        "/opt/homebrew/lib/libmpv.dylib",
        "/opt/homebrew/lib/libmpv.2.dylib",
        "/usr/local/lib/libmpv.dylib",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def ensure_libmpv() -> None:
    if sys.platform != "darwin":
        return
    if ctypes.util.find_library is _patched_find_library:
        return  # already patched
    ctypes.util.find_library = _patched_find_library
