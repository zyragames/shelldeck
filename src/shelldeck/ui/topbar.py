from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from .icons import safe_icon
from .ssh_agent_status import AgentState, KeyInfo, SshAgentStatus, StatusSnapshot


class TopBar(QtWidgets.QToolBar):
    sidebar_toggle_requested = QtCore.Signal()
    settings_requested = QtCore.Signal()
    connect_requested = QtCore.Signal()
    disconnect_requested = QtCore.Signal()
    reconnect_requested = QtCore.Signal()
    copy_ssh_requested = QtCore.Signal()
    clear_requested = QtCore.Signal()
    new_host_requested = QtCore.Signal()
    new_group_requested = QtCore.Signal()
    edit_requested = QtCore.Signal()
    collapsed_changed = QtCore.Signal(bool)

    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setMovable(False)
        self.setFloatable(False)
        self.setIconSize(QtCore.QSize(16, 16))

        self._rail_height = 40
        self._collapsed = False
        self._expanded_height: int | None = None
        self._content_actions: list[QtGui.QAction] = []
        self._content_widgets: list[QtWidgets.QWidget] = []
        self._toggle_button: QtWidgets.QToolButton | None = None

        self._use_ssh_agent: bool = True
        self._ssh_agent_status = SshAgentStatus(self)
        self._ssh_agent_status.set_use_agent_enabled(self._use_ssh_agent)
        self._ssh_agent_status.status_changed.connect(self._apply_ssh_agent_status)
        self._ssh_status_timer = QtCore.QTimer(self)
        self._ssh_status_timer.setInterval(20000)
        self._ssh_status_timer.timeout.connect(self._refresh_ssh_agent)
        self._ssh_status_timer.start()

        self._ssh_status_widget: QtWidgets.QWidget | None = None
        self._ssh_status_label: QtWidgets.QLabel | None = None
        self._ssh_status_dot: QtWidgets.QLabel | None = None
        self._ssh_agent_button: QtWidgets.QToolButton | None = None
        self._ssh_agent_tooltip = ""

        self._build_actions()
        self._build_right_status()
        self._expanded_height = self.sizeHint().height()
        QtCore.QTimer.singleShot(0, self._refresh_ssh_agent)

    def _build_actions(self) -> None:
        actions = [
            ("Connect", "fa5s.plug"),
            ("Disconnect", "fa5s.unlink"),
            ("Reconnect", "fa5s.sync"),
            ("Settings", "fa5s.cog"),
            ("Copy SSH", "fa5s.copy"),
        ]

        for label, icon_name in actions:
            action = QtGui.QAction(safe_icon(icon_name, color="#94a3b8"), label, self)
            if label == "Settings":
                action.triggered.connect(self.settings_requested.emit)
            elif label == "Connect":
                action.triggered.connect(self.connect_requested.emit)
            elif label == "Disconnect":
                action.triggered.connect(self.disconnect_requested.emit)
            elif label == "Reconnect":
                action.triggered.connect(self.reconnect_requested.emit)
            elif label == "Copy SSH":
                action.triggered.connect(self.copy_ssh_requested.emit)
            self.addAction(action)
            self._content_actions.append(action)

    def set_sidebar_collapsed(self, collapsed: bool) -> None:
        return

    def _build_right_status(self) -> None:
        rail_spacer = QtWidgets.QWidget(self)
        rail_spacer.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred
        )
        self.addWidget(rail_spacer)

        status_widget = QtWidgets.QWidget(self)
        layout = QtWidgets.QHBoxLayout(status_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        agent_button = QtWidgets.QToolButton()
        agent_button.setAutoRaise(True)
        agent_button.setIcon(safe_icon("fa5s.sync", color="#94a3b8"))
        agent_button.setIconSize(QtCore.QSize(14, 14))
        agent_button.setToolTip("SSH-Agent Details aktualisieren")
        agent_button.clicked.connect(self._refresh_ssh_agent)
        agent_button.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        agent_button.customContextMenuRequested.connect(self._show_ssh_agent_menu)

        status_label = QtWidgets.QLabel("SSH Agent")
        dot = QtWidgets.QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet("background: #64748b; border-radius: 4px;")

        layout.addWidget(agent_button)
        layout.addWidget(dot)
        layout.addWidget(status_label)

        self.addWidget(status_widget)
        self._content_widgets.append(status_widget)

        self._ssh_status_widget = status_widget
        self._ssh_status_label = status_label
        self._ssh_status_dot = dot
        self._ssh_agent_button = agent_button

        self._toggle_button = None

    def _toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    def _update_toggle_visuals(self) -> None:
        if self._toggle_button is None:
            return
        if self._collapsed:
            icon_name = "fa5s.chevron-down"
            tooltip = "Topbar ausklappen"
        else:
            icon_name = "fa5s.chevron-up"
            tooltip = "Topbar einklappen"
        self._toggle_button.setIcon(safe_icon(icon_name, color="#94a3b8"))
        self._toggle_button.setToolTip(tooltip)

    def _set_content_visible(self, visible: bool) -> None:
        for action in self._content_actions:
            action.setVisible(visible)
        for widget in self._content_widgets:
            widget.setVisible(visible)

    def _current_expanded_height(self) -> int:
        height = self.height()
        if height <= 0:
            height = self.sizeHint().height()
        return max(self._rail_height, height)

    def _apply_height(self, height: int, *, lock: bool) -> None:
        self.setMinimumHeight(height)
        if lock:
            self.setMaximumHeight(height)
        else:
            self.setMaximumHeight(16777215)
        self.updateGeometry()

    def is_collapsed(self) -> bool:
        return self._collapsed

    def expanded_height(self) -> int | None:
        return self._expanded_height

    def restore_state(
        self,
        collapsed: bool,
        expanded_height: int | None,
        *,
        animate: bool = False,
    ) -> None:
        if expanded_height is not None:
            self._expanded_height = max(self._rail_height, expanded_height)
        self.set_collapsed(collapsed, animate=animate)

    def set_collapsed(self, collapsed: bool, *, animate: bool = False) -> None:
        previous = self._collapsed
        if collapsed and not previous:
            self._expanded_height = self._current_expanded_height()

        self._collapsed = collapsed
        self._set_content_visible(not collapsed)
        if collapsed:
            target_height = self._rail_height
        else:
            target_height = self._expanded_height or self._current_expanded_height()
        self._apply_height(target_height, lock=collapsed)
        self._update_toggle_visuals()

        if previous != collapsed:
            self.collapsed_changed.emit(collapsed)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        if not self._collapsed:
            self._expanded_height = max(self._rail_height, self.height())

    def _refresh_ssh_agent(self) -> None:
        self._ssh_agent_status.refresh()

    def _show_ssh_agent_menu(self, position: QtCore.QPoint) -> None:
        if self._ssh_agent_button is None:
            return
        menu = QtWidgets.QMenu(self)
        refresh_action = menu.addAction("Refresh")
        copy_action = menu.addAction("Copy details")
        refresh_action.triggered.connect(self._refresh_ssh_agent)
        copy_action.triggered.connect(self._copy_ssh_agent_details)
        menu.exec(self._ssh_agent_button.mapToGlobal(position))

    def _copy_ssh_agent_details(self) -> None:
        if not self._ssh_agent_tooltip:
            return
        QtGui.QGuiApplication.clipboard().setText(self._ssh_agent_tooltip)

    def _apply_ssh_agent_status(self, snapshot: StatusSnapshot) -> None:
        if self._ssh_status_dot is None or self._ssh_status_widget is None:
            return
        color_map = {
            AgentState.OFF: "#64748b",
            AgentState.OK_KEYS: "#22c55e",
            AgentState.OK_NO_KEYS: "#facc15",
            AgentState.ERROR: "#ef4444",
        }
        dot_color = color_map.get(snapshot.state, "#64748b")
        self._ssh_status_dot.setStyleSheet(f"background: {dot_color}; border-radius: 4px;")
        tooltip = self._build_ssh_agent_tooltip(snapshot)
        self._ssh_agent_tooltip = tooltip
        self._ssh_status_widget.setToolTip(tooltip)
        if self._ssh_status_label is not None:
            self._ssh_status_label.setToolTip(tooltip)
        if self._ssh_status_dot is not None:
            self._ssh_status_dot.setToolTip(tooltip)

    def _build_ssh_agent_tooltip(self, snapshot: StatusSnapshot) -> str:
        use_state = "ON" if snapshot.use_agent_enabled else "OFF"
        reachable = "Yes" if snapshot.agent_reachable else "No"
        keys_loaded = str(snapshot.keys_loaded) if snapshot.keys_loaded is not None else "n/a"
        sock_value = snapshot.ssh_auth_sock or "not set"
        sock_value = self._truncate_text(sock_value, 64)
        lines = [
            "SSH Agent",
            "--------",
            f"Use agent: {use_state}",
            f"SSH_AUTH_SOCK: {sock_value}",
            f"Reachable: {reachable}",
            f"Keys loaded: {keys_loaded}",
        ]

        if snapshot.detected_while_off:
            lines.append("Detected while off: yes")

        if snapshot.keys:
            lines.append("Fingerprints:")
            lines.extend(self._format_key_lines(snapshot.keys))

        last_check = snapshot.last_checked.strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"Last check: {last_check}")
        lines.append(f"Error: {snapshot.last_error or '(none)'}")
        return "\n".join(lines)

    def _format_key_lines(self, keys: tuple[KeyInfo, ...]) -> list[str]:
        max_keys = 3
        lines: list[str] = []
        for key in keys[:max_keys]:
            fingerprint = self._truncate_text(key.fingerprint, 20)
            comment = self._truncate_text(key.comment or "", 32)
            if comment:
                lines.append(f"  {fingerprint} ({comment})")
            else:
                lines.append(f"  {fingerprint}")
        remaining = len(keys) - max_keys
        if remaining > 0:
            lines.append(f"  ... ({remaining} more)")
        return lines

    def _truncate_text(self, value: str, max_length: int) -> str:
        if len(value) <= max_length:
            return value
        return f"{value[: max_length - 3]}..."
