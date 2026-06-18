import locale
import logging
import sys

from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

from wombat.logging_config import configure_logging
from wombat.mpv_loader import ensure_libmpv

log = logging.getLogger(__name__)


def bootstrap() -> int:
    configure_logging(logging.DEBUG)

    # On macOS, ctypes.util.find_library may not find Homebrew's libmpv.
    ensure_libmpv()

    # libmpv requires C numeric locale to parse floats correctly.
    locale.setlocale(locale.LC_NUMERIC, "C")

    # OpenGL core profile ≤4.1 — required for macOS; works everywhere.
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setDepthBufferSize(0)
    fmt.setStencilBufferSize(0)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)
    app.setApplicationName("Wombat")
    app.setOrganizationName("Wombat")

    from wombat.ui.branding import app_icon, make_splash_pixmap
    app.setWindowIcon(app_icon())

    # Splash screen up front, before the (slower) window + player construction.
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QSplashScreen
    splash = QSplashScreen(make_splash_pixmap())
    splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    splash.show()
    app.processEvents()

    # Apply saved theme before creating any windows
    from wombat.settings import AppSettings
    from wombat.ui.theme import apply_dark_theme, apply_light_theme
    _settings = AppSettings()
    if _settings.load_dark_theme():
        apply_dark_theme(app)
    else:
        apply_light_theme(app)

    from wombat.ui.main_window import MainWindow

    win = MainWindow()

    # Keep the splash up for a short minimum, then reveal the window.
    from PySide6.QtCore import QTimer
    _SPLASH_MS = 4000

    def _reveal() -> None:
        win.show()
        splash.finish(win)

    QTimer.singleShot(_SPLASH_MS, _reveal)
    log.info("Wombat started")
    return app.exec()
