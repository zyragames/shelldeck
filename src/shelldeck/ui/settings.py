from __future__ import annotations

from dataclasses import dataclass

from PySide6 import QtCore

DEFAULT_SHOW_TOOLBAR = True


@dataclass(frozen=True)
class UiSettings:
    show_toolbar: bool


def load_ui_settings(settings: QtCore.QSettings) -> UiSettings:
    show_toolbar = settings.value("ui/show_toolbar", DEFAULT_SHOW_TOOLBAR, type=bool)
    if settings.contains("support/kofi_url"):
        settings.remove("support/kofi_url")
    return UiSettings(show_toolbar=bool(show_toolbar))


def save_ui_settings(settings: QtCore.QSettings, config: UiSettings) -> None:
    settings.setValue("ui/show_toolbar", config.show_toolbar)
