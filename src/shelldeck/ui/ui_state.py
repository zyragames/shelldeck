from __future__ import annotations

import logging
from typing import Iterable

from PySide6 import QtCore, QtWidgets

SETTINGS_VERSION = 1
UI_STATE_VERSION_KEY = "ui/state_version"


class UiStateManager:
    def __init__(self, settings: QtCore.QSettings) -> None:
        self._settings = settings
        self._logger = logging.getLogger(__name__)

    def reset_ui_state(self) -> None:
        try:
            self._settings.beginGroup("ui")
            self._settings.remove("")
        finally:
            self._settings.endGroup()
        self._settings.sync()
        self._logger.info("ui state reset settings=%s", self._settings.fileName())

    def load_ui_state(self, window: QtWidgets.QMainWindow) -> None:
        version = self._settings.value(UI_STATE_VERSION_KEY, 0, type=int)
        if isinstance(version, int) and version > SETTINGS_VERSION:
            self._logger.warning(
                "ui state version too new; skipping restore settings=%s version=%s",
                self._settings.fileName(),
                version,
            )
            return
        self._logger.info(
            "ui state restore start settings=%s version=%s",
            self._settings.fileName(),
            version,
        )

        window_mode = self._restore_main_window(window)
        self._restore_splitters(window)
        self._restore_view_headers(window)
        sidebar_collapsed = self._restore_sidebar(window)
        self._restore_sidebar_selection(window)
        topbar_collapsed = self._restore_topbar(window)

        self._logger.info(
            "ui state restored window_mode=%s sidebar_collapsed=%s topbar_collapsed=%s",
            window_mode,
            sidebar_collapsed,
            topbar_collapsed,
        )

    def save_ui_state(self, window: QtWidgets.QMainWindow) -> None:
        window_mode = self._current_window_mode(window)
        self._settings.setValue(UI_STATE_VERSION_KEY, SETTINGS_VERSION)
        self._settings.setValue("ui/main/geometry", window.saveGeometry())
        self._settings.setValue("ui/main/state", window.saveState())
        self._settings.setValue("ui/main/window_mode", window_mode)

        for splitter in self._named_splitters(window):
            self._settings.setValue(
                f"ui/splitter/{splitter.objectName()}/sizes",
                splitter.sizes(),
            )

        for view in self._named_header_views(window):
            header = view.header()
            self._settings.setValue(
                f"ui/view/{view.objectName()}/header_state",
                header.saveState(),
            )

        sidebar = getattr(window, "sidebar", None)
        sidebar_collapsed: bool | None = None
        if sidebar is not None:
            sidebar_collapsed = bool(getattr(sidebar, "is_collapsed", lambda: False)())
            self._settings.setValue("ui/sidebar/collapsed", sidebar_collapsed)
            self._settings.setValue("ui/sidebar/rail_width", sidebar.rail_width())
            last_width = getattr(window, "_sidebar_last_width", None)
            if isinstance(last_width, int):
                self._settings.setValue("ui/sidebar/last_width", last_width)

            selected = getattr(sidebar, "selected_item_key", lambda: None)()
            if selected is None:
                self._settings.remove("ui/sidebar/selection")
            else:
                item_type, item_id = selected
                self._settings.setValue("ui/sidebar/selection/type", item_type)
                self._settings.setValue("ui/sidebar/selection/id", item_id)

        topbar = getattr(window, "topbar", None)
        if topbar is not None:
            is_collapsed = getattr(topbar, "is_collapsed", None)
            if callable(is_collapsed):
                self._settings.setValue("ui/topbar/collapsed", bool(is_collapsed()))
            expanded_height = getattr(topbar, "expanded_height", None)
            if callable(expanded_height):
                height = expanded_height()
                if isinstance(height, int):
                    self._settings.setValue("ui/topbar/expanded_height", height)

        self._settings.sync()
        self._logger.info(
            "ui state saved settings=%s window_mode=%s sidebar_collapsed=%s",
            self._settings.fileName(),
            window_mode,
            sidebar_collapsed,
        )

    def _restore_main_window(self, window: QtWidgets.QMainWindow) -> str:
        geometry = self._settings.value("ui/main/geometry")
        if isinstance(geometry, QtCore.QByteArray):
            window.restoreGeometry(geometry)
        elif isinstance(geometry, (bytes, bytearray)):
            window.restoreGeometry(QtCore.QByteArray(geometry))

        state = self._settings.value("ui/main/state")
        if isinstance(state, QtCore.QByteArray):
            window.restoreState(state)
        elif isinstance(state, (bytes, bytearray)):
            window.restoreState(QtCore.QByteArray(state))

        window_mode = str(self._settings.value("ui/main/window_mode", "normal"))
        self._apply_window_mode(window, window_mode)
        return window_mode

    def _apply_window_mode(self, window: QtWidgets.QMainWindow, mode: str) -> None:
        state = window.windowState()
        maximized_flag = QtCore.Qt.WindowState.WindowMaximized
        fullscreen_flag = QtCore.Qt.WindowState.WindowFullScreen
        if mode == "maximized":
            window.setWindowState(state | maximized_flag)
        elif mode == "fullscreen":
            window.setWindowState(state | fullscreen_flag)
        else:
            window.setWindowState(state & ~maximized_flag & ~fullscreen_flag)

    def _restore_splitters(self, window: QtWidgets.QMainWindow) -> None:
        for splitter in self._named_splitters(window):
            sizes = self._load_int_list(
                self._settings.value(f"ui/splitter/{splitter.objectName()}/sizes")
            )
            if sizes is None or len(sizes) != splitter.count():
                continue
            splitter.setSizes(sizes)

    def _restore_view_headers(self, window: QtWidgets.QMainWindow) -> None:
        for view in self._named_header_views(window):
            state = self._settings.value(f"ui/view/{view.objectName()}/header_state")
            if isinstance(state, QtCore.QByteArray):
                view.header().restoreState(state)
            elif isinstance(state, (bytes, bytearray)):
                view.header().restoreState(QtCore.QByteArray(state))

    def _restore_sidebar(self, window: QtWidgets.QMainWindow) -> bool | None:
        sidebar = getattr(window, "sidebar", None)
        if sidebar is None:
            return None

        collapsed = self._settings.value("ui/sidebar/collapsed", None, type=bool)
        if collapsed is None:
            collapsed = bool(getattr(window, "_sidebar_collapsed", False))
        collapsed = bool(collapsed)

        width_raw = self._settings.value("ui/sidebar/last_width", None)
        width = getattr(window, "_sidebar_last_width", None)
        if width_raw is not None:
            try:
                width = int(width_raw)
            except (TypeError, ValueError):
                width = getattr(window, "_sidebar_last_width", None)

        clamp = getattr(window, "_clamp_sidebar_width", None)
        if width is not None and callable(clamp):
            width = clamp(width)

        if width is not None and hasattr(window, "_sidebar_last_width"):
            window._sidebar_last_width = width
        if hasattr(window, "_sidebar_collapsed"):
            window._sidebar_collapsed = collapsed

        apply_layout = getattr(window, "_apply_sidebar_layout", None)
        if callable(apply_layout):
            apply_layout(collapsed, animate=False)
        else:
            sidebar.set_collapsed(collapsed, lock_width=True)

        topbar = getattr(window, "topbar", None)
        if topbar is not None:
            topbar.set_sidebar_collapsed(collapsed)

        refresh = getattr(window, "_refresh_main_area", None)
        if callable(refresh):
            refresh()

        return collapsed

    def _restore_topbar(self, window: QtWidgets.QMainWindow) -> bool | None:
        topbar = getattr(window, "topbar", None)
        if topbar is None:
            return None
        collapsed_value = self._settings.value("ui/topbar/collapsed", None, type=bool)
        if collapsed_value is None:
            collapsed_value = bool(getattr(topbar, "is_collapsed", lambda: False)())
        collapsed = bool(collapsed_value)

        expanded_raw = self._settings.value("ui/topbar/expanded_height", None)
        expanded_height: int | None = None
        if expanded_raw is not None:
            try:
                expanded_height = int(expanded_raw)
            except (TypeError, ValueError):
                expanded_height = None

        restore = getattr(topbar, "restore_state", None)
        if callable(restore):
            restore(collapsed, expanded_height, animate=False)
        else:
            set_collapsed = getattr(topbar, "set_collapsed", None)
            if callable(set_collapsed):
                set_collapsed(collapsed, animate=False)
        return collapsed

    def _restore_sidebar_selection(self, window: QtWidgets.QMainWindow) -> None:
        sidebar = getattr(window, "sidebar", None)
        restore_selection = getattr(sidebar, "restore_selection", None)
        if sidebar is None or not callable(restore_selection):
            return
        item_type = self._settings.value("ui/sidebar/selection/type", None)
        item_id = self._settings.value("ui/sidebar/selection/id", None)
        if item_type is None or item_id is None:
            return
        try:
            restore_selection(str(item_type), int(item_id))
        except (TypeError, ValueError):
            return

    def _named_splitters(self, window: QtWidgets.QMainWindow) -> Iterable[QtWidgets.QSplitter]:
        for splitter in window.findChildren(QtWidgets.QSplitter):
            if splitter.objectName():
                yield splitter

    def _named_header_views(
        self, window: QtWidgets.QMainWindow
    ) -> Iterable[QtWidgets.QTreeView | QtWidgets.QTableView]:
        for view in window.findChildren(QtWidgets.QTreeView):
            if view.objectName():
                yield view
        for view in window.findChildren(QtWidgets.QTableView):
            if view.objectName():
                yield view

    def _load_int_list(self, value: object) -> list[int] | None:
        if isinstance(value, (list, tuple)):
            items: list[int] = []
            for entry in value:
                try:
                    items.append(int(entry))
                except (TypeError, ValueError):
                    return None
            return items
        return None

    def _current_window_mode(self, window: QtWidgets.QMainWindow) -> str:
        if window.isFullScreen():
            return "fullscreen"
        if window.isMaximized():
            return "maximized"
        return "normal"
