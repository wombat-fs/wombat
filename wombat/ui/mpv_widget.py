"""MpvWidget — libmpv render-API display widget (display only).

Receives the mpv.MPV handle from VideoPlayer; never creates or controls playback.
The render context lives here; VideoPlayer terminates mpv after this widget frees it.

Teardown order (important):
  1. MpvWidget.closeEvent → self._ctx.free()
  2. Caller (MainWindow) → player.shutdown() → mpv.terminate()
"""
import logging
from ctypes import CFUNCTYPE, c_char_p, c_void_p

import mpv
from PySide6 import QtGui
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget

log = logging.getLogger(__name__)

# A custom event type to safely wake the GUI thread from mpv's raw OS thread.
# QCoreApplication.postEvent() is explicitly guaranteed thread-safe by Qt.
_MPV_WAKEUP_TYPE = QEvent.Type(QEvent.registerEventType())

# ctypes function-pointer type matching mpv_opengl_get_proc_address_fn:
#   void *(*fn)(void *ctx, const char *name)
_GlProcAddrFn = CFUNCTYPE(c_void_p, c_void_p, c_char_p)


def _make_get_proc_address() -> _GlProcAddrFn:  # type: ignore[valid-type]
    def _impl(ctx: c_void_p, name: bytes) -> int | None:
        glctx = QtGui.QOpenGLContext.currentContext()
        if glctx is None:
            return None
        addr = glctx.getProcAddress(name.decode("utf-8"))
        # getProcAddress return type varies across PySide6 versions
        if isinstance(addr, int):
            return addr if addr else None
        try:
            v = int(addr)
            return v if v else None
        except (TypeError, ValueError):
            return None

    return _GlProcAddrFn(_impl)


# Module-level singleton — must outlive any MpvRenderContext that uses it.
_GET_PROC_ADDRESS = _make_get_proc_address()


class MpvWidget(QOpenGLWidget):
    """Renders video via libmpv's OpenGL render API inside a QOpenGLWidget.

    Hand it the mpv.MPV instance from VideoPlayer. It only creates a
    MpvRenderContext (in initializeGL) and renders frames (in paintGL).
    """

    def __init__(self, mpv_handle: mpv.MPV, parent=None) -> None:
        super().__init__(parent)
        self._mpv = mpv_handle
        self._ctx: mpv.MpvRenderContext | None = None

    # ----------------------------------------------------------------- GL events

    def initializeGL(self) -> None:
        self._ctx = mpv.MpvRenderContext(
            self._mpv,
            "opengl",
            opengl_init_params={"get_proc_address": _GET_PROC_ADDRESS},
        )
        # update_cb fires on mpv's raw OS thread — postEvent is the only Qt
        # call guaranteed thread-safe from foreign (non-QThread) threads.
        self._ctx.update_cb = lambda: QCoreApplication.postEvent(
            self, QEvent(_MPV_WAKEUP_TYPE)
        )
        log.debug("MpvRenderContext initialized")

    def event(self, e: QEvent) -> bool:
        if e.type() == _MPV_WAKEUP_TYPE:
            if self._ctx is not None:
                self.update()
            return True
        return super().event(e)

    def paintGL(self) -> None:
        if self._ctx is None:
            return
        ratio = self.devicePixelRatioF()
        self._ctx.render(
            flip_y=True,
            opengl_fbo={
                "w": int(self.width() * ratio),
                "h": int(self.height() * ratio),
                "fbo": self.defaultFramebufferObject(),
            },
        )

    # ------------------------------------------------------------------- teardown

    def closeEvent(self, e: QEvent) -> None:
        if self._ctx is not None:
            self._ctx.free()
            self._ctx = None
            log.debug("MpvRenderContext freed")
        super().closeEvent(e)
