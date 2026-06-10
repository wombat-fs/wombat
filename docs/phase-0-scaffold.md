# Phase 0 — Scaffold & Run

**Goal:** a launchable PySide6 application skeleton with the dependency setup, package layout, and dock-based main window in place.

**Milestone (definition of done):** `uv run wombat` (or `python -m wombat`) opens a main window with a menu bar and empty docks, on the developer's machine, with no errors. `pytest` runs and passes a trivial test.

This phase writes almost no logic — it exists to make every later phase a small, runnable increment.

---

## Decisions (firm defaults — change here if you disagree, then proceed)

| Decision | Choice | Rationale |
|---|---|---|
| Python version | **3.11+** | Modern typing, `tomllib` in stdlib; PySide6 + python-mpv both support it. |
| Packaging/deps | **uv** with a PEP 621 `pyproject.toml` | Fast, reproducible; `pyproject` stays pip-compatible (`pip install -e .` works too). |
| Lint/format | **ruff** (lint + format) | One tool, fast. |
| Tests | **pytest** | Standard. |
| Type checking | **mypy** (advisory, not gating yet) | Domain core will be richly typed later. |
| Primary dev platform | **macOS-first (Apple Silicon), cross-platform-aware** | Dev machine and riskiest platform for Phase 1's video. Linux + Windows (x86-64) supported; **Intel macOS out of scope.** Don't add Windows-only or macOS-only code paths without isolating them. |

## Runtime dependencies

- `PySide6` — GUI
- `python-mpv` — video (Phase 1; add the dep now so the env is complete)

## System prerequisite: libmpv

`python-mpv` is a ctypes binding; **libmpv must be installed on the system** (it is not pip-installable). Document this in the README:

- **macOS:** `brew install mpv` (installs `libmpv.dylib`; on Apple Silicon under `/opt/homebrew/lib`)
- **Linux (Debian/Ubuntu):** `sudo apt install libmpv2` (or `libmpv-dev`)
- **Windows:** download a `libmpv-2.dll` and place it on the DLL search path

> Gotcha to anticipate in Phase 1: on macOS, ctypes' `find_library('mpv')` sometimes fails to locate the Homebrew dylib. If so, set `MPV_DYLIB_PATH` or load it explicitly. Note it in the README troubleshooting section, but no code is needed yet.

---

## Package layout to create

```
wombat/
  __init__.py
  __main__.py            # entry: python -m wombat
  app.py                 # bootstrap(): locale, surface format, QApplication, MainWindow
  logging_config.py      # logging setup
  settings.py            # app-settings location/helpers (QSettings wrapper)
  ui/
    __init__.py
    main_window.py       # QMainWindow with menu bar + dock layout
docs/
  phase-0-scaffold.md    # this file
  phase-1-video.md
tests/
  __init__.py
  test_smoke.py          # trivial import/version test
pyproject.toml
.gitignore
README.md                # add a "Development setup" section
```

Empty `domain/`, `playback/`, `app/` packages are **not** created yet — they arrive with the phases that need them (Phase 1 adds `playback/`, Phase 2 adds `domain/`). Keep the skeleton honest: no empty stubs.

---

## Implementation notes

### `pyproject.toml`

PEP 621 metadata. Define:
- `[project]` — name `wombat`, `requires-python = ">=3.11"`, deps `PySide6`, `python-mpv`.
- `[project.scripts]` — `wombat = "wombat.__main__:main"` so `uv run wombat` works.
- `[project.optional-dependencies]` `dev = ["pytest", "ruff", "mypy"]`.
- `[tool.ruff]`, `[tool.pytest.ini_options]` (testpaths = `tests`), `[tool.mypy]` basic config.
- A build backend (`hatchling` is fine).

### `app.py` — bootstrap

Order matters. The surface format and locale **must** be set before the `QApplication` / any GL widget exists (this is here in Phase 0 so Phase 1's video "just works"):

```python
import locale, sys
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

def bootstrap() -> int:
    # libmpv requires the C numeric locale, or it misparses floats.
    locale.setlocale(locale.LC_NUMERIC, "C")

    # Request an OpenGL core profile that works everywhere incl. macOS (≤4.1).
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(0)
    fmt.setStencilBufferSize(0)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)
    app.setApplicationName("Wombat")
    from wombat.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    return app.exec()
```

`__main__.py` exposes `main()` calling `bootstrap()` and `if __name__ == "__main__": raise SystemExit(main())`.

### `ui/main_window.py` — `MainWindow(QMainWindow)`

- **Menu bar** with stub menus: **File** (Open Media…, Open Funscript…, Save Project, Quit), **Edit** (Undo, Redo — disabled), **View** (toggle docks), **Help** (About). Actions can be no-ops/disabled this phase; wire `Quit` and `About`.
- **Dock layout** using `QDockWidget`s with placeholder `QWidget`/`QLabel` contents, arranged to foreshadow the real UI:
  - Central widget: **Video** placeholder (replaced by the mpv widget in Phase 1).
  - Bottom dock: **Timeline** placeholder (Phase 3).
  - Right dock: **Channels / Layers** placeholder (Phases 5–6).
- Give each dock an object name (needed for `saveState`/`restoreState` later).
- Persist/restore window geometry + dock state via `settings.py` on close/open (nice to have; fine to defer the restore).

### `logging_config.py`

A `configure_logging(level)` that sets a root logger with a concise format. Call it from `bootstrap()` before building the window. Use module-level `logging.getLogger(__name__)` everywhere else.

### `settings.py`

Thin wrapper over `QSettings` (org `Wombat`, app `Wombat`) for app-level state (window geometry, recent files). This is the **app-state** half of the app-state/project-state split noted in ROADMAP; project state comes later.

---

## Acceptance criteria

1. Fresh clone → `uv sync` (or `pip install -e ".[dev]"`) installs cleanly.
2. `uv run wombat` opens the window with menu bar + docks; **Quit** and **About** work; no console errors.
3. Window geometry persists across runs (or at minimum, no crash on close).
4. `ruff check` and `ruff format --check` pass.
5. `pytest` runs; `test_smoke.py` asserts `import wombat` works and `PySide6`/`mpv` import.
6. README has a "Development setup" section covering libmpv install per OS.

## Task checklist for the implementer

- [ ] `pyproject.toml` with deps, dev extras, script entry, ruff/pytest/mypy config
- [ ] `.gitignore` (Python, venv, `.uv`, IDE, OS files, reference installations of OFS and funscript-tools already present in the folder)
- [ ] Package skeleton above with `__init__.py`s
- [ ] `app.bootstrap()` with locale + surface format + QApplication
- [ ] `__main__.main()` entry
- [ ] `MainWindow` with menu bar stubs + named docks + placeholders
- [ ] `logging_config.configure_logging()`
- [ ] `settings.py` QSettings wrapper + geometry persistence
- [ ] `tests/test_smoke.py`
- [ ] README "Development setup" + libmpv-per-OS notes
- [ ] Verify all acceptance criteria on macOS
