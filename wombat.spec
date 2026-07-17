# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Wombat.

Build:  pyinstaller wombat.spec --noconfirm
Output: dist/Wombat.app (macOS) / dist/Wombat/ (Windows onedir).

libmpv is special: python-mpv does not import it — it dlopen()s it at runtime
via ctypes — so PyInstaller can't discover it automatically. We bundle it
explicitly from the absolute path in the WOMBAT_LIBMPV env var (set by the CI
workflow or your shell), and the runtime hook packaging/pyi_rth_libmpv.py points
python-mpv at the bundled copy.

macOS caveat (expect to iterate): libmpv drags in a graph of dylibs (ffmpeg,
libass, …). This spec bundles the top-level library; the CI workflow then runs
`dylibbundler` to pull in the transitive deps and rewrite their load paths.
"""
import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH)


def _icon():
    """Best-effort platform icon; None until you generate .icns/.ico from assets/."""
    ext = {"darwin": ".icns", "win32": ".ico"}.get(sys.platform)
    if ext:
        p = ROOT / "assets" / f"wombat{ext}"
        if p.exists():
            return str(p)
    return None


# --- libmpv: absolute path provided by the environment -----------------------
_libmpv = os.environ.get("WOMBAT_LIBMPV", "")
binaries = []
if _libmpv and Path(_libmpv).exists():
    binaries.append((_libmpv, "."))   # bundle root, next to the executable
else:
    print(
        f"WARNING: WOMBAT_LIBMPV unset or missing ({_libmpv!r}); the build will "
        "not include libmpv and video playback will fail at runtime.",
        file=sys.stderr,
    )

# --- data files --------------------------------------------------------------
# assets/ must land at the bundle root: branding.py resolves it as
# Path(__file__).parent.parent.parent / "assets". resources/ is package-relative.
datas = [
    ("assets", "assets"),
    ("wombat/resources", "wombat/resources"),
]

a = Analysis(
    ["wombat/__main__.py"],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["mpv"],       # ctypes wrapper; ensure it ships
    runtime_hooks=["packaging/pyi_rth_libmpv.py"],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Wombat",
    console=False,               # GUI app — no console window
    icon=_icon(),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="Wombat",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Wombat.app",
        icon=_icon(),
        bundle_identifier="me.proton.wombat-fs.wombat",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": os.environ.get("WOMBAT_VERSION", "0.0.0"),
        },
    )
