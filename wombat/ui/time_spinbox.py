"""TimecodeSpinBox — a QDoubleSpinBox whose value is seconds but whose text is a
timeline-style timecode (``m:ss.mmm``, ``h:mm:ss.mmm`` past an hour).

The stored value stays a plain float in seconds, so ``value()``/``setValue()``
behave exactly like a QDoubleSpinBox — only the on-screen text changes. Typing
accepts both timecode (``1:23.5``, ``1:02:03``) and bare seconds (``83.5``), so
users can paste either form.
"""
from __future__ import annotations

from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QDoubleSpinBox

_ALLOWED = set("0123456789:., ")


def format_timecode(seconds: float, decimals: int = 3) -> str:
    """Render seconds as ``m:ss.mmm`` (or ``h:mm:ss.mmm`` once past an hour)."""
    neg = seconds < 0
    s = abs(seconds)
    hours = int(s) // 3600
    mins = (int(s) // 60) % 60
    secs = s % 60
    width = 3 + decimals if decimals else 2  # "ss" plus "." and fraction
    if hours:
        body = f"{hours}:{mins:02d}:{secs:0{width}.{decimals}f}"
    else:
        body = f"{mins}:{secs:0{width}.{decimals}f}"
    return ("-" if neg else "") + body


def parse_timecode(text: str) -> float | None:
    """Parse ``m:ss``/``h:mm:ss``/bare-seconds into seconds. None if unparseable."""
    t = text.strip()
    if t.endswith("s"):          # tolerate a stray "s" suffix
        t = t[:-1].strip()
    neg = t.startswith("-")
    if neg:
        t = t[1:].strip()
    if not t:
        return 0.0
    try:
        parts = [p.strip() for p in t.split(":")]
        seconds = float(parts[-1] or 0.0)
        total = seconds
        mult = 60.0
        for p in reversed(parts[:-1]):
            total += (float(p) if p else 0.0) * mult
            mult *= 60.0
    except ValueError:
        return None
    return -total if neg else total


class TimecodeSpinBox(QDoubleSpinBox):
    """A seconds-valued spin box that shows and accepts timeline timecodes."""

    def textFromValue(self, value: float) -> str:  # noqa: N802 (Qt override)
        return format_timecode(value, self.decimals())

    def valueFromText(self, text: str) -> float:  # noqa: N802 (Qt override)
        parsed = parse_timecode(text)
        return parsed if parsed is not None else self.value()

    def validate(self, text: str, pos: int):  # noqa: N802 (Qt override)
        body = text[len(self.prefix()):] if self.prefix() else text
        if self.suffix():
            body = body[: len(body) - len(self.suffix())]
        body = body.strip()
        if body in ("", "-"):
            return (QValidator.State.Intermediate, text, pos)
        if parse_timecode(body) is not None:
            return (QValidator.State.Acceptable, text, pos)
        if all(c in _ALLOWED or c == "-" for c in body):
            return (QValidator.State.Intermediate, text, pos)
        return (QValidator.State.Invalid, text, pos)
