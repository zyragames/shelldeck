from __future__ import annotations

import logging
import os
import uuid
from typing import Callable, cast

from PySide6 import QtCore, QtGui, QtWidgets

from ..data import Repository
from ..data.models import Host
from ..ssh.command import build_ssh_command
from ..terminal.session import SessionState
from .icons import safe_icon
from .sidebar import Sidebar
from .terminal import TerminalTab
from .theme import ThemeConfig, apply_theme, load_theme_settings, save_theme_settings
from .ui_state import UiStateManager
from .widgets.about_dialog import AboutDialog
from .widgets.settings_dialog import SettingsDialog


class _SplitterDragFilter(QtCore.QObject):
    def __init__(
        self,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_press = on_press
        self._on_release = on_release

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.Type.MouseButtonPress:
            self._on_press()
        if event.type() == QtCore.QEvent.Type.MouseButtonRelease:
            self._on_release()
        return super().eventFilter(watched, event)


class MainWindow(QtWidgets.QMainWindow):
    SIDEBAR_MIN_WIDTH = 200
    SIDEBAR_MAX_WIDTH = 360

    def __init__(self, app: QtWidgets.QApplication) -> None:
        super().__init__()
        self._logger = logging.getLogger(__name__)
        self._debug_layout = os.environ.get("SHELLDECK_DEBUG") == "1"
        self._app = app
        self._repo = Repository.open_default()
        self._settings = QtCore.QSettings()
        self._ui_state_manager = UiStateManager(self._settings)
        self._ui_state_save_timer = QtCore.QTimer(self)
        self._ui_state_save_timer.setSingleShot(True)
        self._ui_state_save_timer.setInterval(250)
        self._ui_state_save_timer.timeout.connect(self._save_ui_state)
        self._app.aboutToQuit.connect(self._save_ui_state)
        self._theme = load_theme_settings(self._settings)
        raw_width = cast(int | str | None, self._settings.value("ui/sidebar/last_width", 280))
        try:
            self._sidebar_last_width = int(raw_width) if raw_width is not None else 280
        except (TypeError, ValueError):
            self._sidebar_last_width = 280
        self._sidebar_last_width = self._clamp_sidebar_width(self._sidebar_last_width)
        self._sidebar_collapsed = bool(
            self._settings.value("ui/sidebar/collapsed", False, type=bool)
        )
        apply_theme(self._app, self._theme)

        self.setWindowTitle("ShellDeck")
        self.setMinimumSize(1200, 720)
        self.setWindowIcon(safe_icon("fa5s.terminal", color="#2dd4bf"))

        self._splitter: QtWidgets.QSplitter | None = None
        self._main_panel: QtWidgets.QWidget | None = None
        self._sidebar_anim: QtCore.QVariantAnimation | None = None
        self._splitter_drag_filter: _SplitterDragFilter | None = None
        self._splitter_dragging = False

        self._build_menu()
        self._build_central()
        self._restore_ui_state()

        self._connected_icon = safe_icon("fa5s.plug", color="#22c55e")
        self._disconnected_icon = safe_icon("fa5s.unlink", color="#64748b")
        self._tab_registry: dict[str, TerminalTab] = {}
        self._tab_key_by_widget: dict[int, str] = {}
        self._closing_tabs: set[TerminalTab] = set()
        self._app_close_in_progress = False
        self._app_close_forced = False
        self._app_close_timer: QtCore.QTimer | None = None

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        exit_action = QtGui.QAction("Exit", self)
        exit_action.setShortcut(QtGui.QKeySequence.StandardKey.Quit)
        exit_action.setStatusTip("Quit ShellDeck")
        exit_action.setToolTip("Quit ShellDeck")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        settings_menu = self.menuBar().addMenu("Settings")
        open_settings_action = QtGui.QAction("Open Settings", self)
        open_settings_action.setShortcut(QtGui.QKeySequence.StandardKey.Preferences)
        open_settings_action.setStatusTip("Open settings dialog")
        open_settings_action.setToolTip("Open settings dialog")
        open_settings_action.triggered.connect(self._open_settings)
        settings_menu.addAction(open_settings_action)

        about_action = QtGui.QAction("About...", self)
        about_action.setStatusTip("About ShellDeck")
        about_action.setToolTip("About ShellDeck")
        about_action.triggered.connect(self._open_about)
        self.menuBar().addAction(about_action)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._enforce_splitter_state("resize")
        if self._debug_layout:
            self._log_layout_snapshot("resize")
        self._post_layout_guard("resize")

    def changeEvent(self, event: QtCore.QEvent) -> None:
        super().changeEvent(event)
        if event.type() != QtCore.QEvent.Type.WindowStateChange:
            return
        self._enforce_splitter_state("window-state-change")
        current_tab = self._current_tab()
        if current_tab is not None:
            current_tab.request_backend_sync()
            QtCore.QTimer.singleShot(50, current_tab.request_backend_sync)
        if self._debug_layout:
            self._log_layout_snapshot("window-state-change")
        self._post_layout_guard("window-state-change")
        self._queue_ui_state_save()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._app_close_forced:
            self._save_ui_state()
            event.accept()
            return
        if self._app_close_in_progress:
            event.ignore()
            return
        active_tabs = [tab for tab in self._active_tabs() if tab.is_alive()]
        if not active_tabs:
            self._save_ui_state()
            super().closeEvent(event)
            return
        event.ignore()
        self._app_close_in_progress = True
        self._logger.info(
            "app close requested; closing sessions count=%s",
            len(active_tabs),
        )
        self._request_close_all_sessions("app_quit")
        timer = QtCore.QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._finalize_app_close("timeout"))
        self._app_close_timer = timer
        timer.start(1200)

    def _build_central(self) -> None:
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setObjectName("mainSplitter")
        splitter.setHandleWidth(1)
        splitter.setOpaqueResize(False)
        splitter.splitterMoved.connect(self._handle_splitter_moved)
        self._splitter = splitter

        self.sidebar = Sidebar(self._repo)
        self.sidebar.set_collapsed(self._sidebar_collapsed)
        self.sidebar.toggle_requested.connect(self._toggle_sidebar)
        self.sidebar.host_activated.connect(self._open_host_tab)
        self.sidebar.host_connect_requested.connect(self._open_host_tab)
        self.sidebar.host_connect_new_tab_requested.connect(self._open_host_tab_new)
        self.sidebar.host_reconnect_requested.connect(self._reconnect_host_sessions)
        self.sidebar.set_session_state_provider(self._has_disconnected_sessions)
        self.sidebar.selection_changed.connect(self._queue_ui_state_save)

        main_panel = QtWidgets.QWidget()
        main_panel.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        main_panel.setMinimumWidth(1)
        self._main_panel = main_panel
        main_layout = QtWidgets.QVBoxLayout(main_panel)
        main_layout.setContentsMargins(16, 12, 16, 16)
        main_layout.setSpacing(12)

        self.tab_bar = QtWidgets.QTabBar()
        self.tab_bar.setExpanding(False)
        self.tab_bar.setAutoHide(False)
        self.tab_bar.setTabsClosable(True)
        self.tab_bar.tabCloseRequested.connect(self._close_tab)
        self.tab_bar.setMovable(True)
        self.tab_bar.currentChanged.connect(self._select_tab)
        self.tab_bar.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.tab_bar.customContextMenuRequested.connect(self._show_tab_menu)
        main_layout.addWidget(self.tab_bar)

        self.tab_stack = QtWidgets.QStackedWidget()
        self._placeholder = QtWidgets.QFrame()
        self._placeholder.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        terminal_layout = QtWidgets.QVBoxLayout(self._placeholder)
        terminal_layout.setContentsMargins(24, 24, 24, 24)
        terminal_layout.addStretch(1)
        placeholder_label = QtWidgets.QLabel("Connect to start...")
        placeholder_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        placeholder_label.setStyleSheet("color: #94a3b8; font-size: 16px;")
        terminal_layout.addWidget(placeholder_label)
        terminal_layout.addStretch(1)
        self.tab_stack.addWidget(self._placeholder)
        self.tab_stack.setCurrentWidget(self._placeholder)
        main_layout.addWidget(self.tab_stack, 1)

        splitter.addWidget(self.sidebar)
        splitter.addWidget(main_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setSizes([self._sidebar_last_width, 900])

        self._splitter_drag_filter = _SplitterDragFilter(
            self._handle_splitter_press,
            self._handle_splitter_release,
            splitter,
        )
        for index in range(1, splitter.count()):
            handle = splitter.handle(index)
            if handle is not None:
                handle.installEventFilter(self._splitter_drag_filter)

        self.setCentralWidget(splitter)

    def _handle_splitter_press(self) -> None:
        self._splitter_dragging = True
        current_tab = self._current_tab()
        if current_tab is not None and current_tab.is_alive():
            current_tab.set_terminal_resize_suspended(True)

    def _handle_splitter_release(self) -> None:
        self._splitter_dragging = False
        current_tab = self._current_tab()
        if current_tab is not None and current_tab.is_alive():
            current_tab.set_terminal_resize_suspended(False)
            current_tab.request_backend_sync(immediate=True)
        self._queue_ui_state_save()

    def _toggle_sidebar(self) -> None:
        self._set_sidebar_collapsed(not self._sidebar_collapsed)

    def _close_tab(self, index: int) -> None:
        widget = self._tab_widget(index)
        if widget is not None:
            self._detach_tab_from_ui(widget)
            self._prepare_tab_close(widget, reason="tab_closed")
            return
        self.tab_bar.removeTab(index)
        if self.tab_bar.count() == 0:
            self.tab_stack.setCurrentWidget(self._placeholder)

    def _detach_tab_from_ui(self, tab: TerminalTab) -> None:
        self._unregister_tab(tab)
        index = self._tab_index(tab)
        if index is not None:
            self.tab_bar.removeTab(index)
        if self.tab_stack.indexOf(tab) >= 0:
            self.tab_stack.removeWidget(tab)
        if self.tab_bar.count() == 0:
            self.tab_stack.setCurrentWidget(self._placeholder)

    def _make_tab_close_button(self) -> QtWidgets.QToolButton:
        button = QtWidgets.QToolButton()
        button.setObjectName("tabCloseButton")
        button.setAutoRaise(True)
        button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        icon = QtGui.QIcon.fromTheme("window-close-symbolic")
        if icon.isNull():
            icon = self.tab_bar.style().standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_TitleBarCloseButton
            )
        button.setIcon(icon)
        button.setIconSize(QtCore.QSize(14, 14))
        button.setFixedSize(QtCore.QSize(22, 22))
        button.clicked.connect(self._handle_tab_close_clicked)
        return button

    def _handle_tab_close_clicked(self) -> None:
        button = self.sender()
        if not isinstance(button, QtWidgets.QToolButton):
            return
        index = -1
        for i in range(self.tab_bar.count()):
            if self.tab_bar.tabButton(i, QtWidgets.QTabBar.ButtonPosition.RightSide) is button:
                index = i
                break
        if index >= 0:
            self.tab_bar.tabCloseRequested.emit(index)

    def _prepare_tab_close(self, tab: TerminalTab, reason: str) -> None:
        if tab in self._closing_tabs:
            return
        self._closing_tabs.add(tab)
        tab.session_closed.connect(lambda _r, widget=tab: self._finalize_tab_close(widget))
        try:
            tab.request_close(reason)
        except Exception:
            self._logger.exception("Failed to close terminal session host=%s", tab.host.name)
            self._finalize_tab_close(tab)

    def _finalize_tab_close(self, tab: TerminalTab) -> None:
        if tab not in self._closing_tabs:
            return
        self._closing_tabs.discard(tab)
        tab.deleteLater()
        if self._app_close_in_progress:
            self._check_app_close_ready()

    def _request_close_all_sessions(self, reason: str) -> None:
        for tab in self._active_tabs(include_closing=True):
            self._detach_tab_from_ui(tab)
            self._prepare_tab_close(tab, reason=reason)

    def _active_tabs(self, include_closing: bool = False) -> list[TerminalTab]:
        tabs: list[TerminalTab] = []
        for index in range(self.tab_bar.count()):
            widget = self.tab_bar.tabData(index)
            if isinstance(widget, TerminalTab):
                tabs.append(widget)
        if include_closing:
            for tab in self._closing_tabs:
                if tab not in tabs:
                    tabs.append(tab)
        return tabs

    def _check_app_close_ready(self) -> None:
        if not self._app_close_in_progress:
            return
        for tab in self._active_tabs(include_closing=True):
            if tab.is_alive():
                return
        self._finalize_app_close("all_sessions_closed")

    def _finalize_app_close(self, reason: str) -> None:
        if self._app_close_forced:
            return
        if self._app_close_timer is not None:
            self._app_close_timer.stop()
        self._app_close_forced = True
        self._logger.info("app closing proceed reason=%s", reason)
        self.close()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(
            self._theme,
            self._repo,
            self,
        )
        dialog.theme_changed.connect(self._apply_theme)
        dialog.data_changed.connect(self.sidebar._reload_tree)
        dialog.layout_reset_requested.connect(self._reset_layout)
        dialog.exec()

    def _open_about(self) -> None:
        dialog = AboutDialog(self)
        dialog.exec()

    def _open_host_tab(self, host: Host) -> None:
        self._open_host_tab_impl(host, allow_existing=True)

    def _open_host_tab_new(self, host: Host) -> None:
        self._open_host_tab_impl(host, allow_existing=False)

    def _open_host_tab_impl(self, host: Host, *, allow_existing: bool) -> None:
        key = self._host_key(host)
        self._logger.info(
            "connect request host_key=%s name=%s hostname=%s user=%s port=%s alias=%s allow_existing=%s",
            key,
            host.name,
            host.hostname,
            host.user,
            host.port,
            host.ssh_config_host_alias,
            allow_existing,
        )
        tab: TerminalTab | None = None
        index: int | None = None
        try:
            if allow_existing:
                existing = self._tab_registry.get(key)
                if existing is not None:
                    index = self._tab_index(existing)
                    if index is not None:
                        self.tab_bar.setCurrentIndex(index)
                        self.tab_stack.setCurrentWidget(existing)
                        self._logger.info("connect request focused existing tab host_key=%s", key)
                        return
                    self._unregister_tab(existing)

            tab = TerminalTab(host, self._theme, self)
            tab.state_changed.connect(
                lambda state, widget=tab: self._update_tab_state(widget, state)
            )
            register_key = key if allow_existing else f"{key}:dup:{uuid.uuid4().hex}"
            self._register_tab(register_key, tab)
            self.tab_stack.addWidget(tab)
            index = self.tab_bar.addTab(self._disconnected_icon, host.name)
            self.tab_bar.setTabButton(
                index,
                QtWidgets.QTabBar.ButtonPosition.RightSide,
                self._make_tab_close_button(),
            )
            self.tab_bar.setTabData(index, tab)
            self.tab_bar.setCurrentIndex(index)
            self.tab_stack.setCurrentWidget(tab)

            self._logger.info(
                "connect session start host_key=%s target=%s user=%s port=%s command=%s",
                register_key,
                tab.command_spec.target,
                tab.command_spec.user,
                tab.command_spec.port,
                tab.command_spec.display,
            )
            started = tab.connect_session()
            if not started:
                self._show_connect_error(host.name, "Could not start SSH session.")
        except Exception:
            self._logger.exception("connect flow failed for host_key=%s", key)
            if tab is not None:
                self._unregister_tab(tab)
                if self.tab_stack.indexOf(tab) >= 0:
                    self.tab_stack.removeWidget(tab)
                if index is not None:
                    self.tab_bar.removeTab(index)
                tab.deleteLater()
            self._show_connect_error(host.name, "Connect failed.")

    def _connect_selected_host(self) -> None:
        try:
            host = self.sidebar.selected_host()
            if host is None:
                QtWidgets.QMessageBox.information(self, "No host", "Select a host to connect.")
                return
            self._open_host_tab(host)
        except Exception:
            self._logger.exception("connect action failed")
            self._show_connect_error("selected host", "Connect failed.")

    def _disconnect_current_tab(self) -> None:
        tab = self._current_tab()
        if tab is None:
            return
        try:
            tab.disconnect_session()
        except Exception:
            self._logger.exception("disconnect action failed for host=%s", tab.host.name)

    def _reconnect_current_tab(self) -> None:
        tab = self._current_tab()
        if tab is None:
            return
        try:
            started = tab.reconnect_session()
            if not started:
                self._show_connect_error(tab.host.name, "Reconnect failed.")
        except Exception:
            self._logger.exception("reconnect action failed for host=%s", tab.host.name)
            self._show_connect_error(tab.host.name, "Reconnect failed.")

    def _clear_current_terminal(self) -> None:
        tab = self._current_tab()
        if tab is None:
            return
        try:
            tab.clear_terminal()
        except Exception:
            self._logger.exception("clear terminal failed for host=%s", tab.host.name)

    def _show_tab_menu(self, pos: QtCore.QPoint) -> None:
        index = self.tab_bar.tabAt(pos)
        if index < 0:
            return
        tab = self._tab_widget(index)
        if tab is None:
            return

        menu = QtWidgets.QMenu(self)
        menu.addSection("Session")

        duplicate_action = menu.addAction("Duplicate Tab")
        duplicate_action.triggered.connect(lambda: self._open_host_tab_new(tab.host))

        state = tab.session_state()
        if state in {SessionState.ERROR, SessionState.CLOSED}:
            reconnect_action = menu.addAction("Reconnect")
            reconnect_action.triggered.connect(lambda: self._reconnect_tab(tab))
        if state == SessionState.CONNECTED:
            disconnect_action = menu.addAction("Disconnect")
            disconnect_action.triggered.connect(lambda: self._disconnect_tab(tab))

        close_action = menu.addAction("Close Tab")
        close_action.triggered.connect(lambda: self._close_tab(index))

        menu.addSeparator()
        menu.addSection("Terminal")

        clear_action = menu.addAction("Clear Screen")
        clear_action.triggered.connect(lambda: tab.clear_terminal())

        zoom_menu = menu.addMenu("Zoom")
        zoom_in = zoom_menu.addAction("Zoom In")
        zoom_in.triggered.connect(lambda: tab.zoom_in())
        zoom_out = zoom_menu.addAction("Zoom Out")
        zoom_out.triggered.connect(lambda: tab.zoom_out())
        zoom_reset = zoom_menu.addAction("Reset Zoom")
        zoom_reset.triggered.connect(lambda: tab.reset_zoom())

        menu.addSeparator()
        menu.addSection("Close")

        close_all = menu.addAction("Close All Sessions")
        close_all.triggered.connect(self._confirm_close_all_sessions)

        menu.exec(self.tab_bar.mapToGlobal(pos))

    def _confirm_close_all_sessions(self) -> None:
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Close all sessions",
            "Close all sessions?",
        )
        if confirm != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self._request_close_all_sessions("menu_close_all")

    def _disconnect_tab(self, tab: TerminalTab) -> None:
        try:
            tab.disconnect_session()
        except Exception:
            self._logger.exception("disconnect action failed for host=%s", tab.host.name)

    def _reconnect_tab(self, tab: TerminalTab) -> None:
        try:
            started = tab.reconnect_session()
            if not started:
                self._show_connect_error(tab.host.name, "Reconnect failed.")
        except Exception:
            self._logger.exception("reconnect action failed for host=%s", tab.host.name)
            self._show_connect_error(tab.host.name, "Reconnect failed.")

    def _reconnect_host_sessions(self, host: Host) -> None:
        for tab in self._tabs_for_host(host):
            if tab.session_state() in {SessionState.ERROR, SessionState.CLOSED}:
                self._reconnect_tab(tab)

    def _has_disconnected_sessions(self, host: Host) -> bool:
        for tab in self._tabs_for_host(host):
            if tab.session_state() in {SessionState.ERROR, SessionState.CLOSED}:
                return True
        return False

    def _tabs_for_host(self, host: Host) -> list[TerminalTab]:
        matches: list[TerminalTab] = []
        for tab in self._active_tabs(include_closing=True):
            if self._is_same_host(tab.host, host):
                matches.append(tab)
        return matches

    def _is_same_host(self, left: Host, right: Host) -> bool:
        if left.id is not None and right.id is not None:
            return left.id == right.id
        if left.ssh_config_host_alias and right.ssh_config_host_alias:
            return left.ssh_config_host_alias == right.ssh_config_host_alias
        left_user = left.user or ""
        right_user = right.user or ""
        left_port = left.port if left.port is not None else 22
        right_port = right.port if right.port is not None else 22
        return (
            left.hostname == right.hostname and left_user == right_user and left_port == right_port
        )

    def _copy_current_ssh(self) -> None:
        try:
            tab = self._current_tab()
            if tab is None:
                host = self.sidebar.selected_host()
                if host is None:
                    return
                command = build_ssh_command(host)
            else:
                command = tab.command_spec
            QtWidgets.QApplication.clipboard().setText(command.display)
        except Exception:
            self._logger.exception("copy ssh command failed")

    def _select_tab(self, index: int) -> None:
        widget = self._tab_widget(index)
        if widget is None:
            if self.tab_bar.count() == 0:
                self.tab_stack.setCurrentWidget(self._placeholder)
            return
        self.tab_stack.setCurrentWidget(widget)

    def _current_tab(self) -> TerminalTab | None:
        index = self.tab_bar.currentIndex()
        return self._tab_widget(index)

    def _tab_widget(self, index: int) -> TerminalTab | None:
        if index < 0:
            return None
        widget = self.tab_bar.tabData(index)
        if isinstance(widget, TerminalTab):
            return widget
        return None

    def _update_tab_state(self, tab: TerminalTab, state: str) -> None:
        index = self._tab_index(tab)
        if index is None:
            return
        icon = self._connected_icon if state == "connected" else self._disconnected_icon
        suffixes = {
            "connecting": "connecting",
            "closing": "closing",
            "error": "error",
            "closed": "disconnected",
        }
        if state == "connected":
            label = tab.host.name
        else:
            suffix = suffixes.get(state, "disconnected")
            label = f"{tab.host.name} ({suffix})"
        self.tab_bar.setTabIcon(index, icon)
        self.tab_bar.setTabText(index, label)

    def _tab_index(self, widget: TerminalTab) -> int | None:
        for index in range(self.tab_bar.count()):
            if self.tab_bar.tabData(index) is widget:
                return index
        return None

    def _host_key(self, host: Host) -> str:
        if host.id is not None:
            return f"id:{host.id}"
        if host.ssh_config_host_alias:
            return f"alias:{host.ssh_config_host_alias}"
        user_prefix = f"{host.user}@" if host.user else ""
        port = host.port if host.port is not None else 22
        return f"host:{user_prefix}{host.hostname}:{port}"

    def _register_tab(self, key: str, tab: TerminalTab) -> None:
        self._tab_registry[key] = tab
        self._tab_key_by_widget[id(tab)] = key

    def _unregister_tab(self, tab: TerminalTab) -> None:
        key = self._tab_key_by_widget.pop(id(tab), None)
        if key and self._tab_registry.get(key) is tab:
            self._tab_registry.pop(key, None)

    def _apply_theme(self, config: ThemeConfig) -> None:
        self._theme = config
        save_theme_settings(self._settings, self._theme)
        apply_theme(self._app, self._theme)
        self._apply_terminal_theme()

    def _set_sidebar_collapsed(
        self,
        collapsed: bool,
        persist: bool = True,
        *,
        animate: bool = True,
    ) -> None:
        splitter = self._splitter
        if splitter is None:
            return
        if self._debug_layout:
            self._log_layout_snapshot("toggle-sidebar-before")
        if collapsed:
            sizes = splitter.sizes()
            current_width = sizes[0] if sizes else 0
            if current_width > self.sidebar.rail_width() + 8:
                self._sidebar_last_width = self._clamp_sidebar_width(current_width)
        self._apply_sidebar_layout(collapsed, animate=animate)
        self._sidebar_collapsed = collapsed
        self._refresh_main_area()
        self._post_layout_guard("toggle-sidebar")
        if self._debug_layout:
            self._log_layout_snapshot("toggle-sidebar-after")
        if persist:
            self._queue_ui_state_save()

    def _splitter_total(
        self,
        splitter: QtWidgets.QSplitter,
        sizes: list[int] | None = None,
    ) -> int:
        if sizes is None:
            sizes = splitter.sizes()
        total = sum(sizes) if sizes else 0
        if total <= 1:
            total = splitter.width()
        return max(1, total)

    def _refresh_main_area(self) -> None:
        if self._main_panel is None:
            return
        central = self.centralWidget()
        if central is not None:
            central_layout = cast(QtWidgets.QLayout | None, central.layout())
            if central_layout is not None:
                central_layout.invalidate()
                central_layout.activate()
        self._main_panel.updateGeometry()
        self._main_panel.update()
        self.tab_bar.updateGeometry()
        self.tab_bar.update()
        self.tab_stack.updateGeometry()
        self.tab_stack.update()

    def _handle_splitter_moved(self, _pos: int, _index: int) -> None:
        splitter = self._splitter
        if splitter is None:
            return
        sizes = splitter.sizes()
        if not sizes:
            return
        rail_width = self.sidebar.rail_width()
        if sizes[0] <= rail_width + 2:
            if not self._sidebar_collapsed:
                self._set_sidebar_collapsed(True, animate=False)
            return
        if self._sidebar_collapsed and sizes[0] > rail_width + 8:
            self._sidebar_collapsed = False
            self.sidebar.set_collapsed(False)
        max_width = self.SIDEBAR_MAX_WIDTH
        if sizes[0] > max_width:
            total = self._splitter_total(splitter, sizes)
            splitter.setSizes([max_width, max(1, total - max_width)])
            sizes = splitter.sizes()
        self._sidebar_last_width = self._clamp_sidebar_width(sizes[0])
        if self._sidebar_collapsed:
            self._sidebar_collapsed = False
            self.sidebar.set_collapsed(False)
        if not self._splitter_dragging:
            self._queue_ui_state_save()

    def _clamp_sidebar_width(self, width: int) -> int:
        return max(self.SIDEBAR_MIN_WIDTH, min(self.SIDEBAR_MAX_WIDTH, width))

    def _apply_sidebar_layout(self, collapsed: bool, *, animate: bool = True) -> None:
        splitter = self._splitter
        if splitter is None:
            return
        sizes = splitter.sizes()
        total = self._splitter_total(splitter, sizes)
        target_width = (
            self.sidebar.rail_width()
            if collapsed
            else self._clamp_sidebar_width(self._sidebar_last_width)
        )
        target_width = min(target_width, max(1, total - 1))
        if not animate:
            self.sidebar.set_collapsed(collapsed, lock_width=True)
            splitter.setSizes([target_width, max(1, total - target_width)])
            return
        if self._sidebar_anim is not None:
            self._sidebar_anim.stop()
        self.sidebar.set_collapsed(collapsed, lock_width=False)
        start_width = sizes[0] if sizes else target_width
        start_width = min(start_width, max(1, total - 1))
        anim = QtCore.QVariantAnimation(self)
        anim.setStartValue(start_width)
        anim.setEndValue(target_width)
        anim.setDuration(180)
        anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)

        def apply_width(value: object) -> None:
            if isinstance(value, (int, float)):
                width = int(value)
            else:
                width = target_width
            width = min(width, max(1, total - 1))
            splitter.setSizes([width, max(1, total - width)])

        def finalize() -> None:
            self.sidebar.set_collapsed(collapsed, lock_width=True)

        anim.valueChanged.connect(apply_width)
        anim.finished.connect(finalize)
        self._sidebar_anim = anim
        anim.start()

    def _enforce_splitter_state(self, reason: str) -> None:
        splitter = self._splitter
        if splitter is None:
            return
        sizes = splitter.sizes()
        if len(sizes) < 2:
            return
        total = self._splitter_total(splitter, sizes)
        if self._sidebar_collapsed and sizes[0] != self.sidebar.rail_width():
            splitter.setSizes(
                [self.sidebar.rail_width(), max(1, total - self.sidebar.rail_width())]
            )
            if self._debug_layout:
                self._logger.debug(
                    "enforce splitter collapsed reason=%s sizes=%s total=%s",
                    reason,
                    sizes,
                    total,
                )
            return
        if not self._sidebar_collapsed and sizes[1] <= 1:
            self._apply_sidebar_layout(False, animate=False)
            if self._debug_layout:
                self._logger.debug(
                    "enforce splitter expanded reason=%s sizes=%s total=%s",
                    reason,
                    sizes,
                    total,
                )
            return
        if not self._sidebar_collapsed and sizes[0] > self.SIDEBAR_MAX_WIDTH:
            splitter.setSizes([self.SIDEBAR_MAX_WIDTH, max(1, total - self.SIDEBAR_MAX_WIDTH)])

    def _post_layout_guard(self, reason: str) -> None:
        if self.tab_bar.height() > 0 and self.tab_stack.height() > 80:
            return
        self.tab_bar.setAutoHide(False)
        self.tab_bar.show()
        central = self.centralWidget()
        if central is not None:
            central_layout = cast(QtWidgets.QLayout | None, central.layout())
            if central_layout is not None:
                central_layout.invalidate()
                central_layout.activate()
        self._refresh_main_area()
        self._logger.warning(
            "layout guard triggered reason=%s tabbar_h=%s tabstack_h=%s",
            reason,
            self.tab_bar.height(),
            self.tab_stack.height(),
        )
        if self._debug_layout:
            self._log_layout_snapshot(f"guard-{reason}")

    def _restore_ui_state(self) -> None:
        try:
            self._ui_state_manager.load_ui_state(self)
        except Exception:
            self._logger.exception("ui state restore failed")
        self._post_layout_guard("restore-ui-state")

    def _reset_layout(self) -> None:
        try:
            self._ui_state_manager.reset_ui_state()
        except Exception:
            self._logger.exception("ui state reset failed")
        self.apply_default_layout()
        self._save_ui_state()
        QtWidgets.QMessageBox.information(
            self,
            "Layout zurückgesetzt",
            "Layout wurde zurückgesetzt",
        )

    def apply_default_layout(self) -> None:
        if self._sidebar_anim is not None:
            self._sidebar_anim.stop()
        self._ui_state_save_timer.stop()
        self.showNormal()
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        target_width = 1200
        target_height = 720
        if screen is not None:
            available = screen.availableGeometry()
            width = min(target_width, available.width())
            height = min(target_height, available.height())
            self.resize(width, height)
            self.move(available.center() - self.rect().center())
        else:
            self.resize(target_width, target_height)

        self._sidebar_last_width = self._clamp_sidebar_width(280)
        self._sidebar_collapsed = False
        self._apply_sidebar_layout(False, animate=False)

        splitter = self._splitter
        if splitter is not None:
            total = self._splitter_total(splitter)
            sidebar_width = min(self._sidebar_last_width, max(1, total - 1))
            splitter.setSizes([sidebar_width, max(1, total - sidebar_width)])

        for view in self.findChildren(QtWidgets.QTreeView):
            if view.objectName():
                view.header().reset()
        for view in self.findChildren(QtWidgets.QTableView):
            if view.objectName():
                view.horizontalHeader().reset()

        self._refresh_main_area()

    def _queue_ui_state_save(self) -> None:
        self._ui_state_save_timer.start()

    def _save_ui_state(self) -> None:
        try:
            self._ui_state_manager.save_ui_state(self)
        except Exception:
            self._logger.exception("ui state save failed")

    def _log_layout_snapshot(self, reason: str) -> None:
        splitter = self._splitter
        splitter_sizes = splitter.sizes() if splitter is not None else []
        current = self._current_tab()
        terminal_container = current.findChild(QtWidgets.QWidget) if current is not None else None
        self._logger.debug(
            "layout snapshot reason=%s window=%sx%s tabbar_h=%s tabstack=%s current_tab=%s terminal_container=%s splitter=%s",
            reason,
            self.width(),
            self.height(),
            self.tab_bar.height(),
            self.tab_stack.geometry().getRect(),
            current.geometry().getRect() if current is not None else None,
            terminal_container.geometry().getRect() if terminal_container is not None else None,
            splitter_sizes,
        )
        self._dump_widget_tree(self, reason=reason)

    def _dump_widget_tree(
        self,
        root: QtWidgets.QWidget,
        *,
        reason: str,
        max_depth: int = 6,
    ) -> None:
        def walk(widget: QtWidgets.QWidget, depth: int) -> None:
            if depth > max_depth:
                return
            policy = widget.sizePolicy()
            geom = widget.geometry()
            name = widget.objectName() or "-"
            self._logger.debug(
                "tree reason=%s depth=%s class=%s name=%s visible=%s geom=(%s,%s,%s,%s) policy=(%s,%s) min=(%s,%s) max=(%s,%s)",
                reason,
                depth,
                widget.metaObject().className(),
                name,
                widget.isVisible(),
                geom.x(),
                geom.y(),
                geom.width(),
                geom.height(),
                policy.horizontalPolicy(),
                policy.verticalPolicy(),
                widget.minimumWidth(),
                widget.minimumHeight(),
                widget.maximumWidth(),
                widget.maximumHeight(),
            )
            if isinstance(widget, QtWidgets.QSplitter):
                self._logger.debug(
                    "tree reason=%s depth=%s splitter_sizes=%s",
                    reason,
                    depth,
                    widget.sizes(),
                )
            children = widget.findChildren(
                QtWidgets.QWidget, options=QtCore.Qt.FindChildOption.FindDirectChildrenOnly
            )
            for child in children:
                walk(child, depth + 1)

        walk(root, 0)

    def _apply_terminal_theme(self) -> None:
        for index in range(self.tab_bar.count()):
            widget = self.tab_bar.tabData(index)
            if isinstance(widget, TerminalTab):
                widget.apply_theme(self._theme)

    def _show_connect_error(self, host_label: str, reason: str) -> None:
        QtWidgets.QMessageBox.warning(
            self,
            "Connect failed",
            f"{reason}\nHost: {host_label}\nSee ~/.cache/shelldeck/shelldeck.log",
        )
