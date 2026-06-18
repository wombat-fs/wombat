"""Branding assets — app icon and startup splash screen.

Assets live in the repo-root ``assets/`` directory (the same layout used by
``events_panel`` for the bundled event YAML). Paths are resolved relative to
this file so they work whether run from source or an installed checkout.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap

_ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"

# App-icon PNGs to fold into a single multi-resolution QIcon.
_APPICON_SIZES = (128, 256, 512, 1024)

# Splash card colours (light card so the dark "Wombat" lockup reads well).
_CARD_BG = QColor("#fbf8f2")      # warm cream
_CARD_BORDER = QColor("#e6e1d6")
_TAGLINE_FG = QColor("#8a8578")


def asset_path(*parts: str) -> Path:
    return _ASSETS_DIR.joinpath(*parts)


def app_icon() -> QIcon:
    """Multi-resolution app icon assembled from the PNG appicons."""
    icon = QIcon()
    for size in _APPICON_SIZES:
        path = asset_path("png", f"wombat-appicon-{size}.png")
        if path.exists():
            icon.addFile(str(path))
    return icon


def make_splash_pixmap() -> QPixmap:
    """Compose a tidy splash card with the lockup centered on a cream panel."""
    dpr = 1.0
    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        dpr = screen.devicePixelRatio()

    width, height = 560, 300
    canvas = QPixmap(int(width * dpr), int(height * dpr))
    canvas.setDevicePixelRatio(dpr)
    canvas.fill(Qt.GlobalColor.transparent)

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    # Rounded card
    card = QRectF(0.5, 0.5, width - 1.0, height - 1.0)
    painter.setBrush(_CARD_BG)
    painter.setPen(_CARD_BORDER)
    painter.drawRoundedRect(card, 24.0, 24.0)

    # Lockup, scaled to fit with side margins
    lockup = QPixmap(str(asset_path("wombat-lockup.png")))
    if not lockup.isNull():
        target_w = width - 120
        scaled = lockup.scaledToWidth(
            int(target_w * dpr), Qt.TransformationMode.SmoothTransformation
        )
        scaled.setDevicePixelRatio(dpr)
        x = (width - scaled.width() / dpr) / 2.0
        y = (height - scaled.height() / dpr) / 2.0 - 14.0
        painter.drawPixmap(int(x), int(y), scaled)

    # Tagline
    font = painter.font()
    font.setPointSizeF(font.pointSizeF() * 1.05)
    painter.setFont(font)
    painter.setPen(_TAGLINE_FG)
    painter.drawText(
        QRectF(0, height - 56, width, 28),
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
        "Cross-platform funscript authoring",
    )
    painter.end()
    return canvas
