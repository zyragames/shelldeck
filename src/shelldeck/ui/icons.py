from __future__ import annotations

import logging

from PySide6 import QtGui
import qtawesome as qta


_LOG = logging.getLogger(__name__)


def safe_icon(
    name: str,
    *,
    fallback: str | None = "fa5s.question-circle",
    **kwargs,
) -> QtGui.QIcon:
    try:
        return qta.icon(name, **kwargs)
    except Exception as exc:
        _LOG.warning("Failed to load icon '%s': %s", name, exc)

    if fallback and fallback != name:
        try:
            return qta.icon(fallback, **kwargs)
        except Exception as exc:
            _LOG.warning("Failed to load fallback icon '%s': %s", fallback, exc)

    return QtGui.QIcon()
