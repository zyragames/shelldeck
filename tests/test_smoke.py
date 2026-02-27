from __future__ import annotations

from PySide6 import QtCore

from shelldeck.data import Repository
from shelldeck.ui.settings import UiSettings, load_ui_settings, save_ui_settings
from shelldeck.ui.theme import load_theme_settings


def test_db_init_and_settings_load(tmp_path) -> None:
    repo = Repository.open(tmp_path / "shelldeck.db")
    assert repo.list_groups() == []
    repo.close()

    if QtCore.QCoreApplication.instance() is None:
        QtCore.QCoreApplication([])

    settings = QtCore.QSettings(
        str(tmp_path / "settings.ini"),
        QtCore.QSettings.Format.IniFormat,
    )

    theme = load_theme_settings(settings)
    assert theme.mode in {"dark", "light"}

    save_ui_settings(
        settings,
        UiSettings(show_toolbar=False),
    )
    settings.sync()

    ui_settings = load_ui_settings(settings)
    assert ui_settings.show_toolbar is False
