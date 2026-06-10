import importlib


def test_wombat_importable():
    import wombat

    assert wombat.__version__ == "0.1.0"


def test_pyside6_importable():
    mod = importlib.import_module("PySide6.QtWidgets")
    assert mod is not None


def test_mpv_importable():
    mod = importlib.import_module("mpv")
    assert mod is not None
