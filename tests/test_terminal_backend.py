from __future__ import annotations

import importlib.util

from PySide6 import QtWidgets

from shelldeck.terminal.backend import FallbackBackend, TermQtBackend, create_terminal_backend


_APP: QtWidgets.QApplication | None = None


def test_terminal_backend_smoke() -> None:
    global _APP
    if QtWidgets.QApplication.instance() is None:
        _APP = QtWidgets.QApplication([])

    backend = create_terminal_backend(None)
    assert backend.widget() is not None

    termqt_available = importlib.util.find_spec("termqt") is not None
    if termqt_available:
        assert isinstance(backend, TermQtBackend)
    else:
        assert isinstance(backend, FallbackBackend)

    backend.clear()
    backend.close()
