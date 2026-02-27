from __future__ import annotations

import logging
from dataclasses import replace
import socket
import time
import sqlite3
from pathlib import Path
from typing import Callable

from PySide6 import QtCore, QtGui, QtWidgets

from ..data import Repository
from ..data.models import Group, Host
from ..ssh.command import build_ssh_command
from .icons import safe_icon
from .widgets.group_dialog import GroupDialog
from .widgets.host_dialog import HostDialog


ROLE_TYPE = QtCore.Qt.ItemDataRole.UserRole + 1
ROLE_ID = QtCore.Qt.ItemDataRole.UserRole + 2
ROLE_NAME = QtCore.Qt.ItemDataRole.UserRole + 3
ROLE_HOSTNAME = QtCore.Qt.ItemDataRole.UserRole + 4
ROLE_TAGS = QtCore.Qt.ItemDataRole.UserRole + 5
ROLE_FAVORITE = QtCore.Qt.ItemDataRole.UserRole + 6
ROLE_LAST_USED = QtCore.Qt.ItemDataRole.UserRole + 7
KOFI_PRIMARY_URL = "https://ko-fi.com/I2I4K45FK"
KOFI_FALLBACK_URL = "https://ko-fi.com/zyrano"
KOFI_REMOTE_IMAGE = "https://storage.ko-fi.com/cdn/kofi6.png?v=6"
KOFI_LOCAL_IMAGE = Path(__file__).resolve().parent / "assets" / "support_me_on_kofi_badge_red.png"


class _HostPingWorker(QtCore.QObject, QtCore.QRunnable):
    finished = QtCore.Signal(bool, str)

    def __init__(self, host: Host, timeout: float = 2.0) -> None:
        QtCore.QObject.__init__(self)
        QtCore.QRunnable.__init__(self)
        self._host = host
        self._timeout = timeout

    def run(self) -> None:
        start = time.perf_counter()
        hostname = self._host.hostname
        port = self._host.port or 22
        try:
            socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except socket.gaierror:
            self.finished.emit(False, "DNS failed")
            return
        except Exception as exc:
            self.finished.emit(False, f"DNS failed: {exc}")
            return
        try:
            with socket.create_connection((hostname, port), timeout=self._timeout):
                pass
        except socket.timeout:
            self.finished.emit(False, "Timeout")
            return
        except OSError as exc:
            self.finished.emit(False, f"Connection failed: {exc}")
            return
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        self.finished.emit(True, f"OK ({elapsed_ms}ms)")


class HostFilterProxyModel(QtCore.QSortFilterProxyModel):
    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._filter_text = ""

    def set_filter_text(self, text: str) -> None:
        self._filter_text = text.strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(
        self,
        source_row: int,
        source_parent: QtCore.QModelIndex | QtCore.QPersistentModelIndex,
    ) -> bool:
        if not self._filter_text:
            return True
        model = self.sourceModel()
        index = model.index(source_row, 0, source_parent)
        if not index.isValid():
            return False
        item_type = model.data(index, ROLE_TYPE)
        name = str(model.data(index, ROLE_NAME) or "").lower()
        hostname = str(model.data(index, ROLE_HOSTNAME) or "").lower()
        tags = model.data(index, ROLE_TAGS) or []
        if item_type == "group":
            if self._match_text(name, "", []):
                return True
            for row in range(model.rowCount(index)):
                if self.filterAcceptsRow(row, index):
                    return True
            return False
        return self._match_text(name, hostname, tags)

    def _match_text(self, name: str, hostname: str, tags: list[str]) -> bool:
        combined = " ".join([name, hostname, " ".join(tags)]).lower()
        return self._filter_text in combined


class Sidebar(QtWidgets.QWidget):
    toggle_requested = QtCore.Signal()
    host_activated = QtCore.Signal(Host)
    selection_changed = QtCore.Signal()
    host_connect_requested = QtCore.Signal(Host)
    host_connect_new_tab_requested = QtCore.Signal(Host)
    host_reconnect_requested = QtCore.Signal(Host)
    RAIL_WIDTH = 44
    EXPANDED_MIN_WIDTH = 200

    def __init__(
        self,
        repository: Repository,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._logger = logging.getLogger(__name__)
        self._collapsed = False
        self._repo = repository
        self._has_disconnected_session: Callable[[Host], bool] | None = None
        self._ping_workers: set[_HostPingWorker] = set()

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._rail = QtWidgets.QWidget()
        self._rail.setFixedWidth(self.RAIL_WIDTH)
        rail_layout = QtWidgets.QVBoxLayout(self._rail)
        rail_layout.setContentsMargins(8, 10, 8, 10)
        rail_layout.setSpacing(8)

        self._toggle_button = QtWidgets.QToolButton()
        self._toggle_button.setIcon(safe_icon("fa5s.angle-left", color="#94a3b8"))
        self._toggle_button.setToolTip("Toggle sidebar")
        self._toggle_button.clicked.connect(self.toggle_requested.emit)
        rail_layout.addWidget(self._toggle_button, alignment=QtCore.Qt.AlignmentFlag.AlignTop)
        rail_layout.addStretch(1)
        self._toggle_button.setVisible(self._collapsed)

        self._content = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(self._content)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(10)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(8)

        icon_label = QtWidgets.QLabel()
        icon_label.setPixmap(safe_icon("fa5s.layer-group", color="#2dd4bf").pixmap(18, 18))
        title = QtWidgets.QLabel("ShellDeck")
        title_font = QtGui.QFont()
        title_font.setPointSize(13)
        title_font.setWeight(QtGui.QFont.Weight.DemiBold)
        title.setFont(title_font)

        self._header_toggle_button = QtWidgets.QToolButton()
        self._header_toggle_button.setIcon(safe_icon("fa5s.angle-left", color="#94a3b8"))
        self._header_toggle_button.setToolTip("Toggle sidebar")
        self._header_toggle_button.clicked.connect(self.toggle_requested.emit)

        header.addWidget(icon_label)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self._header_toggle_button)
        content_layout.addLayout(header)

        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search hosts, groups, tags...")
        content_layout.addWidget(self.search)

        self.tree = QtWidgets.QTreeView()
        self.tree.setObjectName("sidebarTree")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setAnimated(True)
        self.tree.setWordWrap(True)
        self.tree.setUniformRowHeights(False)

        self.model = QtGui.QStandardItemModel(self.tree)
        self.proxy = HostFilterProxyModel(self.tree)
        self.proxy.setSourceModel(self.model)
        self.tree.setModel(self.proxy)
        self.tree.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        content_layout.addWidget(self.tree, 1)

        self.tree.doubleClicked.connect(self._handle_tree_activated)
        self.tree.selectionModel().selectionChanged.connect(self._handle_selection_changed)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)

        self.search.textChanged.connect(self.proxy.set_filter_text)

        footer = QtWidgets.QWidget()
        footer_layout = QtWidgets.QVBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(8)

        footer_divider = QtWidgets.QFrame()
        footer_divider.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        footer_divider.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        footer_layout.addWidget(footer_divider)

        button_bar = QtWidgets.QHBoxLayout()
        button_bar.setSpacing(8)
        self.add_host_button = QtWidgets.QPushButton()
        self.add_group_button = QtWidgets.QPushButton()
        self.edit_button = QtWidgets.QPushButton()
        self.delete_button = QtWidgets.QPushButton()
        button_bar.addWidget(self.add_host_button)
        button_bar.addWidget(self.add_group_button)
        button_bar.addWidget(self.edit_button)
        button_bar.addWidget(self.delete_button)
        footer_layout.addLayout(button_bar)

        self.kofi_button = QtWidgets.QToolButton()
        self.kofi_button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.kofi_button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.kofi_button.setAutoRaise(True)
        self.kofi_button.setStyleSheet(
            "QToolButton { padding: 0px; margin: 0px; border: none; background: transparent; }"
            "QToolButton:hover { background: transparent; }"
            "QToolButton:pressed { background: transparent; }"
            "QToolButton:focus { outline: none; }"
        )
        self.kofi_button.clicked.connect(self._open_kofi)

        badge_width = int(self.EXPANDED_MIN_WIDTH * 0.5)
        badge_pixmap = QtGui.QPixmap(str(KOFI_LOCAL_IMAGE))
        if not badge_pixmap.isNull():
            scaled = badge_pixmap.scaledToWidth(
                badge_width,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            self.kofi_button.setIcon(QtGui.QIcon(scaled))
            self.kofi_button.setIconSize(scaled.size())
            self.kofi_button.setFixedSize(scaled.size())
        else:
            self.kofi_button.setText("Support on Ko-fi")
        footer_layout.addWidget(self.kofi_button, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)

        content_layout.addWidget(footer)

        layout.addWidget(self._rail)
        layout.addWidget(self._content, 1)

        self.add_host_button.clicked.connect(self._add_host)
        self.add_group_button.clicked.connect(self._add_group)
        self.edit_button.clicked.connect(self._edit_selected)
        self.delete_button.clicked.connect(self._delete_selected)

        self._action_buttons = [
            (self.add_host_button, "New Host", "fa5s.plus"),
            (self.add_group_button, "New Group", "fa5s.folder-plus"),
            (self.edit_button, "Edit", "fa5s.edit"),
            (self.delete_button, "Delete", "fa5s.trash"),
        ]
        self._apply_action_button_mode()

        self._reload_tree()
        self._update_action_states()

    def set_collapsed(self, collapsed: bool, *, lock_width: bool = True) -> None:
        self._collapsed = collapsed
        self._content.setVisible(not collapsed)
        self._rail.setVisible(collapsed)
        icon_name = "fa5s.chevron-right" if collapsed else "fa5s.chevron-left"
        self._toggle_button.setIcon(safe_icon(icon_name, color="#94a3b8"))
        self._header_toggle_button.setIcon(safe_icon(icon_name, color="#94a3b8"))
        self._toggle_button.setVisible(collapsed)
        if collapsed:
            self._rail.setFixedWidth(self.RAIL_WIDTH)
            self.setMinimumWidth(self.RAIL_WIDTH)
            self.setMaximumWidth(self.RAIL_WIDTH if lock_width else 16777215)
        else:
            self._rail.setFixedWidth(0)
            self.setMaximumWidth(16777215)
            self.setMinimumWidth(self.EXPANDED_MIN_WIDTH if lock_width else self.RAIL_WIDTH)
        self._apply_action_button_mode()

    def rail_width(self) -> int:
        return self.RAIL_WIDTH

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_session_state_provider(self, provider: Callable[[Host], bool]) -> None:
        self._has_disconnected_session = provider

    def selected_item_key(self) -> tuple[str, int] | None:
        index = self._selected_source_index()
        if index is None:
            return None
        item_type = self.model.data(index, ROLE_TYPE)
        item_id = self.model.data(index, ROLE_ID)
        if item_type not in {"group", "host"} or item_id is None:
            return None
        return str(item_type), int(item_id)

    def restore_selection(self, item_type: str, item_id: int) -> None:
        source_index = self._find_item_index(item_type, item_id)
        if source_index is None:
            return
        proxy_index = self.proxy.mapFromSource(source_index)
        if not proxy_index.isValid():
            return
        selection_model = self.tree.selectionModel()
        if selection_model is None:
            return
        selection_model.setCurrentIndex(
            proxy_index,
            QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect
            | QtCore.QItemSelectionModel.SelectionFlag.Rows,
        )
        parent_index = source_index.parent()
        if parent_index.isValid():
            proxy_parent = self.proxy.mapFromSource(parent_index)
            if proxy_parent.isValid():
                self.tree.expand(proxy_parent)

    def _find_item_index(self, item_type: str, item_id: int) -> QtCore.QModelIndex | None:
        for row in range(self.model.rowCount()):
            group_item = self.model.item(row)
            if group_item is None:
                continue
            if item_type == "group":
                if group_item.data(ROLE_TYPE) == "group" and group_item.data(ROLE_ID) == item_id:
                    return group_item.index()
            elif item_type == "host":
                for child_row in range(group_item.rowCount()):
                    host_item = group_item.child(child_row)
                    if host_item is None:
                        continue
                    if host_item.data(ROLE_TYPE) == "host" and host_item.data(ROLE_ID) == item_id:
                        return host_item.index()
        return None

    def _apply_action_button_mode(self) -> None:
        for button, label, icon_name in self._action_buttons:
            button.setIcon(safe_icon(icon_name, color="#94a3b8"))
            button.setToolTip(label)
            button.setText("")

    def _open_kofi(self) -> None:
        link_target = KOFI_PRIMARY_URL or KOFI_FALLBACK_URL
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(link_target))

    def _reload_tree(self) -> None:
        self.model.clear()
        for group, hosts in self._repo.list_groups_with_hosts():
            group_item = QtGui.QStandardItem(group.name)
            group_item.setData("group", ROLE_TYPE)
            group_item.setData(group.id, ROLE_ID)
            group_item.setData(group.name, ROLE_NAME)
            group_item.setIcon(safe_icon("fa5s.folder", color="#94a3b8"))

            for host in hosts:
                name = self._format_host_name(host)
                detail = self._format_host_detail(host)
                host_item = QtGui.QStandardItem(f"{name}\n{detail}")
                host_item.setData("host", ROLE_TYPE)
                host_item.setData(host.id, ROLE_ID)
                host_item.setData(host.name, ROLE_NAME)
                host_item.setData(host.hostname, ROLE_HOSTNAME)
                tags = list(host.tags)
                if host.tag:
                    tags.append(host.tag)
                host_item.setData(tags, ROLE_TAGS)
                host_item.setData(host.favorite, ROLE_FAVORITE)
                host_item.setData(None, ROLE_LAST_USED)
                host_item.setIcon(safe_icon("fa5s.server", color=self._host_icon_color(host)))
                host_item.setToolTip(self._build_host_tooltip(host))
                group_item.appendRow(host_item)

            self.model.appendRow(group_item)
            self.tree.expand(self.proxy.mapFromSource(group_item.index()))
        self._update_action_states()

    def _format_host_name(self, host: Host) -> str:
        prefix = "* " if host.favorite else ""
        return f"{prefix}{host.name}"

    def _format_host_detail(self, host: Host) -> str:
        user = f"{host.user}@" if host.user else ""
        port = host.port if host.port else 22
        detail = f"{user}{host.hostname}:{port}"
        if host.tag:
            detail = f"{detail} [{host.tag}]"
        return detail

    def _host_icon_color(self, host: Host) -> str:
        if host.color:
            color = QtGui.QColor(host.color)
            if color.isValid():
                return host.color
        return "#2dd4bf"

    def _build_host_tooltip(self, host: Host) -> str:
        lines = [f"Host: {host.hostname}"]
        if host.user:
            lines.append(f"User: {host.user}")
        if host.port:
            lines.append(f"Port: {host.port}")
        if host.favorite:
            lines.append("Favorite: yes")
        if host.tag:
            lines.append(f"Tag: {host.tag}")
        if host.color:
            lines.append(f"Color: {host.color}")
        if host.tags:
            lines.append(f"Tags: {', '.join(host.tags)}")
        return "\n".join(lines)

    def _selected_source_index(self) -> QtCore.QModelIndex | None:
        index = self.tree.selectionModel().currentIndex()
        if not index.isValid():
            return None
        return self.proxy.mapToSource(index)

    def selected_host(self) -> Host | None:
        index = self._selected_source_index()
        if index is None:
            return None
        if self.model.data(index, ROLE_TYPE) != "host":
            return None
        item_id = self.model.data(index, ROLE_ID)
        if item_id is None:
            return None
        return self._repo.get_host(int(item_id))

    def _show_context_menu(self, pos: QtCore.QPoint) -> None:
        index = self.tree.indexAt(pos)
        if not index.isValid():
            return
        source_index = self.proxy.mapToSource(index)
        if not source_index.isValid():
            return
        item_type = self.model.data(source_index, ROLE_TYPE)
        item_id = self.model.data(source_index, ROLE_ID)
        if item_type not in {"group", "host"} or item_id is None:
            return
        self.tree.setCurrentIndex(index)
        if item_type == "host":
            host = self._repo.get_host(int(item_id))
            if host is None:
                return
            self._show_host_menu(host, pos)
            return
        group = self._repo.get_group(int(item_id))
        if group is None:
            return
        self._show_group_menu(group, source_index, pos)

    def _handle_tree_activated(self, index: QtCore.QModelIndex) -> None:
        try:
            source_index = self.proxy.mapToSource(index)
            if not source_index.isValid():
                return
            if self.model.data(source_index, ROLE_TYPE) != "host":
                return
            item_id = self.model.data(source_index, ROLE_ID)
            if item_id is None:
                return
            host = self._repo.get_host(int(item_id))
            if host is None:
                return
            self.host_activated.emit(host)
        except Exception:
            self._logger.exception("host activation failed")
            QtWidgets.QMessageBox.warning(
                self,
                "Connect failed",
                "Host activation failed. See ~/.cache/shelldeck/shelldeck.log",
            )

    def _show_host_menu(self, host: Host, pos: QtCore.QPoint) -> None:

        menu = QtWidgets.QMenu(self)
        menu.addSection("Connect")

        connect_action = menu.addAction("Connect")
        connect_action.triggered.connect(lambda: self.host_connect_requested.emit(host))

        connect_new_action = menu.addAction("Connect in New Tab")
        connect_new_action.triggered.connect(lambda: self.host_connect_new_tab_requested.emit(host))

        if self._has_disconnected_session and self._has_disconnected_session(host):
            reconnect_action = menu.addAction("Reconnect")
            reconnect_action.triggered.connect(lambda: self.host_reconnect_requested.emit(host))

        menu.addSeparator()
        menu.addSection("Edit")

        edit_action = menu.addAction("Edit…")
        edit_action.triggered.connect(lambda: self._edit_host(host))

        rename_action = menu.addAction("Rename")
        rename_action.triggered.connect(lambda: self._rename_host(host))

        duplicate_action = menu.addAction("Duplicate")
        duplicate_action.triggered.connect(lambda: self._duplicate_host(host))

        menu.addSeparator()
        menu.addSection("Copy")

        copy_menu = menu.addMenu("Copy")
        copy_host = copy_menu.addAction("Copy Host")
        copy_host.triggered.connect(lambda: self._copy_text(host.hostname))

        user_host = f"{host.user}@{host.hostname}" if host.user else host.hostname
        copy_user_host = copy_menu.addAction("Copy User@Host")
        copy_user_host.triggered.connect(lambda: self._copy_text(user_host))

        port_value = str(host.port if host.port is not None else 22)
        copy_port = copy_menu.addAction("Copy Port")
        copy_port.triggered.connect(lambda: self._copy_text(port_value))

        ssh_command = build_ssh_command(host).display
        copy_ssh = copy_menu.addAction("Copy SSH Command")
        copy_ssh.triggered.connect(lambda: self._copy_text(ssh_command))

        full_connection = self._build_full_connection_string(host)
        if full_connection:
            copy_full = copy_menu.addAction("Copy Full Connection String")
            copy_full.triggered.connect(lambda: self._copy_text(full_connection))

        menu.addSeparator()
        menu.addSection("Organize")

        group_menu = menu.addMenu("Move to Group…")
        groups = self._repo.list_groups()
        for group in groups:
            action = group_menu.addAction(group.name)
            if group.id == host.group_id:
                action.setEnabled(False)
            else:
                action.triggered.connect(
                    lambda _checked=False, gid=group.id: self._move_host_to_group(host, gid)
                )
        group_menu.addSeparator()
        new_group_action = group_menu.addAction("New Group…")
        new_group_action.triggered.connect(lambda: self._move_host_to_new_group(host))

        favorite_label = "Remove from Favorites" if host.favorite else "Add to Favorites"
        favorite_action = menu.addAction(favorite_label)
        favorite_action.triggered.connect(lambda: self._toggle_favorite(host))

        color_action = menu.addAction("Set Color/Tag…")
        color_action.triggered.connect(lambda: self._edit_color_tag(host))

        menu.addSeparator()
        menu.addSection("Tools")

        ping_action = menu.addAction("Ping / Test Connection")
        ping_action.triggered.connect(lambda: self._test_connection(host))

        menu.addSeparator()
        menu.addSection("Danger")

        delete_action = menu.addAction("Delete…")
        delete_action.setIcon(safe_icon("fa5s.trash", color="#ef4444"))
        delete_action.triggered.connect(lambda: self._delete_host(host))

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _show_group_menu(
        self,
        group: Group,
        source_index: QtCore.QModelIndex,
        pos: QtCore.QPoint,
    ) -> None:
        menu = QtWidgets.QMenu(self)
        menu.addSection("Create")

        new_server_action = menu.addAction("New Server…")
        new_server_action.triggered.connect(lambda: self._add_host_in_group(group))

        new_group_action = menu.addAction("New Group…")
        new_group_action.triggered.connect(self._add_group)

        menu.addSeparator()
        menu.addSection("Manage")

        rename_action = menu.addAction("Rename Group")
        rename_action.triggered.connect(lambda: self._rename_group(group))

        duplicate_action = menu.addAction("Duplicate Group")
        duplicate_action.triggered.connect(lambda: self._duplicate_group(group))

        menu.addSeparator()
        menu.addSection("View")

        proxy_index = self.proxy.mapFromSource(source_index)
        is_expanded = self.tree.isExpanded(proxy_index)
        expand_label = "Collapse Group" if is_expanded else "Expand Group"
        expand_action = menu.addAction(expand_label)
        expand_action.triggered.connect(lambda: self._toggle_group_expanded(proxy_index))

        group_item = self.model.itemFromIndex(source_index)
        if group_item is not None and group_item.rowCount() > 0:
            collapse_all_action = menu.addAction("Collapse All")
            collapse_all_action.triggered.connect(self.tree.collapseAll)

        menu.addSeparator()
        menu.addSection("Organize")

        sort_menu = menu.addMenu("Sort Servers")
        sort_name_action = sort_menu.addAction("By Name")
        sort_name_action.triggered.connect(lambda: self._sort_group_hosts(group.id, "name"))

        sort_favorites_action = sort_menu.addAction("Favorites First")
        sort_favorites_action.triggered.connect(
            lambda: self._sort_group_hosts(group.id, "favorites")
        )

        if self._group_has_last_used(group_item):
            sort_last_used_action = sort_menu.addAction("By Last Used")
            sort_last_used_action.triggered.connect(
                lambda: self._sort_group_hosts(group.id, "last_used")
            )

        menu.addSeparator()
        menu.addSection("Danger")

        delete_action = menu.addAction("Delete Group…")
        delete_action.setIcon(safe_icon("fa5s.trash", color="#ef4444"))
        delete_action.triggered.connect(lambda: self._delete_group(group))

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _copy_text(self, text: str) -> None:
        QtGui.QGuiApplication.clipboard().setText(text)

    def _build_full_connection_string(self, host: Host) -> str | None:
        user_prefix = f"{host.user}@" if host.user else ""
        port_suffix = f":{host.port}" if host.port else ""
        extras = []
        if host.ssh_config_host_alias:
            extras.append(f"alias={host.ssh_config_host_alias}")
        if host.identity_file:
            extras.append(f"key={host.identity_file}")
        if not (user_prefix or port_suffix or extras):
            return None
        base = f"{user_prefix}{host.hostname}{port_suffix}"
        if extras:
            return f"{base} ({', '.join(extras)})"
        return base

    def _edit_host(self, host: Host) -> None:
        dialog = HostDialog(self._repo.list_groups(), host=host, parent=self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        form = dialog.form_data()
        try:
            self._repo.update_host(form.host)
        except sqlite3.IntegrityError:
            QtWidgets.QMessageBox.warning(
                self, "Duplicate host", "Host with same hostname exists in this group."
            )
            return
        self._reload_tree()
        self.restore_selection("host", host.id)

    def _rename_host(self, host: Host) -> None:
        new_name, ok = QtWidgets.QInputDialog.getText(
            self,
            "Rename host",
            "New name:",
            text=host.name,
        )
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name or new_name == host.name:
            return
        updated = replace(host, name=new_name)
        try:
            self._repo.update_host(updated)
        except sqlite3.IntegrityError:
            QtWidgets.QMessageBox.warning(
                self, "Duplicate host", "Host with same hostname exists in this group."
            )
            return
        self._reload_tree()
        self.restore_selection("host", host.id)

    def _duplicate_host(self, host: Host) -> None:
        clone = replace(host, id=0, name=f"{host.name} Copy")
        dialog = HostDialog(self._repo.list_groups(), host=clone, parent=self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        form = dialog.form_data()
        try:
            created = self._repo.create_host(form.host)
        except sqlite3.IntegrityError:
            QtWidgets.QMessageBox.warning(
                self, "Duplicate host", "Host with same hostname exists in this group."
            )
            return
        self._reload_tree()
        self.restore_selection("host", created.id)

    def _delete_host(self, host: Host) -> None:
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Delete host",
            "Delete this host?",
        )
        if confirm != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self._repo.delete_host(host.id)
        self._reload_tree()

    def _move_host_to_group(self, host: Host, group_id: int) -> None:
        updated = replace(host, group_id=group_id)
        try:
            self._repo.update_host(updated)
        except sqlite3.IntegrityError:
            QtWidgets.QMessageBox.warning(
                self, "Duplicate host", "Host with same hostname exists in this group."
            )
            return
        self._reload_tree()
        self.restore_selection("host", host.id)

    def _move_host_to_new_group(self, host: Host) -> None:
        dialog = GroupDialog(parent=self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        name = dialog.group_name()
        try:
            group = self._repo.create_group(name)
        except sqlite3.IntegrityError:
            QtWidgets.QMessageBox.warning(self, "Duplicate group", "Group name exists.")
            return
        self._move_host_to_group(host, group.id)

    def _toggle_favorite(self, host: Host) -> None:
        updated = replace(host, favorite=not host.favorite)
        self._repo.update_host(updated)
        self._reload_tree()
        self.restore_selection("host", host.id)

    def _edit_color_tag(self, host: Host) -> None:
        color = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(host.color) if host.color else QtGui.QColor(),
            self,
            "Pick color",
        )
        if not color.isValid():
            return
        color_hex = color.name()
        tag, ok = QtWidgets.QInputDialog.getText(
            self,
            "Set tag",
            "Tag:",
            text=host.tag or "",
        )
        if not ok:
            return
        tag = tag.strip() or None
        updated = replace(host, color=color_hex, tag=tag)
        self._repo.update_host(updated)
        self._reload_tree()
        self.restore_selection("host", host.id)

    def _test_connection(self, host: Host) -> None:
        worker = _HostPingWorker(host)
        self._ping_workers.add(worker)

        def handle_result(ok: bool, message: str) -> None:
            self._ping_workers.discard(worker)
            title = "Connection OK" if ok else "Connection failed"
            QtWidgets.QMessageBox.information(self, title, f"{host.name}: {message}")

        worker.finished.connect(handle_result)
        QtCore.QThreadPool.globalInstance().start(worker)

    def _add_group(self) -> None:
        dialog = GroupDialog(parent=self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        name = dialog.group_name()
        try:
            self._repo.create_group(name)
        except sqlite3.IntegrityError:
            QtWidgets.QMessageBox.warning(self, "Duplicate group", "Group name exists.")
            return
        self._reload_tree()

    def _add_host_in_group(self, group: Group) -> None:
        groups = self._repo.list_groups()
        if not groups:
            QtWidgets.QMessageBox.information(
                self, "No groups", "Create a group before adding a host."
            )
            return
        dialog = HostDialog(groups, parent=self)
        index = dialog.group_combo.findData(group.id)
        if index >= 0:
            dialog.group_combo.setCurrentIndex(index)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        form = dialog.form_data()
        try:
            created = self._repo.create_host(form.host)
        except sqlite3.IntegrityError:
            QtWidgets.QMessageBox.warning(
                self, "Duplicate host", "Host with same hostname exists in this group."
            )
            return
        self._reload_tree()
        self.restore_selection("host", created.id)

    def _add_host(self) -> None:
        groups = self._repo.list_groups()
        if not groups:
            QtWidgets.QMessageBox.information(
                self, "No groups", "Create a group before adding a host."
            )
            return
        dialog = HostDialog(groups, parent=self)
        selected_group_id = self._selected_group_id()
        if selected_group_id is not None:
            index = dialog.group_combo.findData(selected_group_id)
            if index >= 0:
                dialog.group_combo.setCurrentIndex(index)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        form = dialog.form_data()
        try:
            self._repo.create_host(form.host)
        except sqlite3.IntegrityError:
            QtWidgets.QMessageBox.warning(
                self, "Duplicate host", "Host with same hostname exists in this group."
            )
            return
        self._reload_tree()

    def _edit_selected(self) -> None:
        index = self._selected_source_index()
        if index is None:
            return
        item_type = self.model.data(index, ROLE_TYPE)
        item_id = self.model.data(index, ROLE_ID)
        if item_type == "group":
            group = self._repo.get_group(int(item_id))
            if not group:
                return
            self._rename_group(group)
            return
        if item_type == "host":
            host = self._repo.get_host(int(item_id))
            if not host:
                return
            dialog = HostDialog(self._repo.list_groups(), host=host, parent=self)
            if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                return
            form = dialog.form_data()
            try:
                self._repo.update_host(form.host)
            except sqlite3.IntegrityError:
                QtWidgets.QMessageBox.warning(
                    self, "Duplicate host", "Host with same hostname exists in this group."
                )
                return
            self._reload_tree()

    def _delete_selected(self) -> None:
        index = self._selected_source_index()
        if index is None:
            return
        item_type = self.model.data(index, ROLE_TYPE)
        item_id = self.model.data(index, ROLE_ID)
        if item_type == "group":
            group = self._repo.get_group(int(item_id))
            if not group:
                return
            self._delete_group(group)
            return
        if item_type == "host":
            confirm = QtWidgets.QMessageBox.question(
                self,
                "Delete host",
                "Delete this host?",
            )
            if confirm != QtWidgets.QMessageBox.StandardButton.Yes:
                return
            self._repo.delete_host(int(item_id))
            self._reload_tree()

    def _rename_group(self, group: Group) -> None:
        dialog = GroupDialog(name=group.name, parent=self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        try:
            self._repo.update_group(group.id, dialog.group_name())
        except sqlite3.IntegrityError:
            QtWidgets.QMessageBox.warning(self, "Duplicate group", "Group name exists.")
            return
        self._reload_tree()
        self.restore_selection("group", group.id)

    def _duplicate_group(self, group: Group) -> None:
        dialog = GroupDialog(name=f"{group.name} Copy", parent=self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        name = dialog.group_name()
        try:
            created_group = self._repo.create_group(name)
        except sqlite3.IntegrityError:
            QtWidgets.QMessageBox.warning(self, "Duplicate group", "Group name exists.")
            return
        for host in self._repo.list_hosts_for_group(group.id):
            clone = replace(host, id=0, group_id=created_group.id)
            self._repo.create_host(clone)
        self._reload_tree()
        self.restore_selection("group", created_group.id)

    def _delete_group(self, group: Group) -> None:
        hosts = self._repo.list_hosts_for_group(group.id)
        confirm = QtWidgets.QMessageBox(self)
        confirm.setWindowTitle("Delete group")
        confirm.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        confirm.setText(f"Delete the group '{group.name}'?")
        confirm.setInformativeText(
            "Servers will be moved to 'Ungrouped' unless you choose to delete them."
        )
        confirm.setStandardButtons(
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.Cancel
        )
        confirm.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Cancel)
        delete_hosts_checkbox = QtWidgets.QCheckBox("Also delete servers in this group")
        delete_hosts_checkbox.setChecked(False)
        confirm.setCheckBox(delete_hosts_checkbox)
        if confirm.exec() != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        if delete_hosts_checkbox.isChecked() or not hosts:
            self._repo.delete_group(group.id)
            self._reload_tree()
            return
        fallback = self._select_fallback_group(group, hosts)
        for host in hosts:
            updated = replace(host, group_id=fallback.id)
            self._repo.update_host(updated)
        self._repo.delete_group(group.id)
        self._reload_tree()
        self.restore_selection("group", fallback.id)

    def _select_fallback_group(self, group: Group, hosts: list[Host]) -> Group:
        groups = self._repo.list_groups()
        for existing in groups:
            if existing.name == "Ungrouped" and existing.id != group.id:
                if not hosts:
                    return existing
                existing_hosts = self._repo.list_hosts_for_group(existing.id)
                existing_hostnames = {host.hostname for host in existing_hosts}
                if not any(host.hostname in existing_hostnames for host in hosts):
                    return existing
                break
        name = self._unique_group_name("Ungrouped", exclude_id=group.id)
        return self._repo.create_group(name)

    def _unique_group_name(self, base: str, *, exclude_id: int | None = None) -> str:
        names = {
            group.name
            for group in self._repo.list_groups()
            if exclude_id is None or group.id != exclude_id
        }
        if base not in names:
            return base
        suffix = 1
        while True:
            candidate = f"{base} ({suffix})"
            if candidate not in names:
                return candidate
            suffix += 1

    def _toggle_group_expanded(self, proxy_index: QtCore.QModelIndex) -> None:
        if self.tree.isExpanded(proxy_index):
            self.tree.collapse(proxy_index)
        else:
            self.tree.expand(proxy_index)

    def _group_has_last_used(self, group_item: QtGui.QStandardItem | None) -> bool:
        if group_item is None:
            return False
        for row in range(group_item.rowCount()):
            child = group_item.child(row)
            if child is None:
                continue
            if child.data(ROLE_LAST_USED) is not None:
                return True
        return False

    def _sort_group_hosts(self, group_id: int, mode: str) -> None:
        source_index = self._find_item_index("group", group_id)
        if source_index is None:
            return
        group_item = self.model.itemFromIndex(source_index)
        if group_item is None:
            return
        rows = []
        while group_item.rowCount():
            rows.append(group_item.takeRow(0))
        if mode == "favorites":
            key_fn = self._sort_key_favorites
        elif mode == "last_used":
            key_fn = self._sort_key_last_used
        else:
            key_fn = self._sort_key_name

        rows.sort(key=key_fn)
        for row in rows:
            group_item.appendRow(row)

    def _sort_key_favorites(self, row: list[QtGui.QStandardItem]) -> tuple[int, str, str]:
        item = row[0]
        favorite = bool(item.data(ROLE_FAVORITE))
        name = str(item.data(ROLE_NAME) or "").lower()
        return (0 if favorite else 1, name, "")

    def _sort_key_last_used(self, row: list[QtGui.QStandardItem]) -> tuple[int, str, str]:
        item = row[0]
        last_used = item.data(ROLE_LAST_USED)
        name = str(item.data(ROLE_NAME) or "").lower()
        value = str(last_used) if last_used is not None else ""
        return (0 if last_used is not None else 1, value, name)

    def _sort_key_name(self, row: list[QtGui.QStandardItem]) -> tuple[int, str, str]:
        item = row[0]
        return (0, str(item.data(ROLE_NAME) or "").lower(), "")

    def _handle_selection_changed(
        self,
        _selected: QtCore.QItemSelection,
        _deselected: QtCore.QItemSelection,
    ) -> None:
        self._update_action_states()
        self.selection_changed.emit()

    def _update_action_states(self) -> None:
        index = self._selected_source_index()
        if index is None:
            self.edit_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            return
        item_type = self.model.data(index, ROLE_TYPE)
        enabled = item_type in {"group", "host"}
        self.edit_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)

    def _selected_group_id(self) -> int | None:
        index = self._selected_source_index()
        if index is None:
            return None
        item_type = self.model.data(index, ROLE_TYPE)
        if item_type == "group":
            return int(self.model.data(index, ROLE_ID))
        if item_type == "host":
            parent_index = index.parent()
            if parent_index.isValid():
                return int(self.model.data(parent_index, ROLE_ID))
        return None
