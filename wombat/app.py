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

    from wombat.ui.main_window import MainWindow

    win = MainWindow()
    win.show()
    log.info("Wombat started")
    return app.exec()
