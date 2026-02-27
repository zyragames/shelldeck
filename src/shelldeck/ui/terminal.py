from __future__ import annotations

import logging
import os
import shlex
from typing import Any, cast

from PySide6 import QtCore, QtGui, QtWidgets

from ..data.models import Host
from ..ssh.command import build_ssh_command
from ..terminal.backend import (
    FallbackBackend,
    TerminalTheme,
    TermQtBackend,
    create_terminal_backend,
)
from ..terminal.session import SessionController, SessionState
from .theme import ThemeConfig

MIN_PT = 7
MAX_PT = 26
DEFAULT_PT = 11


class TerminalTab(QtWidgets.QWidget):
    state_changed = QtCore.Signal(str)
    session_closed = QtCore.Signal(str)

    def __init__(
        self,
        host: Host,
        theme: ThemeConfig | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("terminalTab")
        self._logger = logging.getLogger(__name__)
        self.host = host
        self.command_spec = build_ssh_command(host)
        self._backend = create_terminal_backend(self)
        self._session = self._init_session_controller()
        self._pending_reconnect = False
        self._base_font = self._resolve_base_font()
        self._base_zoom_size, self._base_zoom_mode = _get_font_size(self._base_font)
        self._zoom_size = self._base_zoom_size
        self._zoom_mode = self._base_zoom_mode
        self._set_zoom_property(self._zoom_size, self._zoom_mode)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        backend_widget = self._backend.widget()
        backend_widget.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        layout.addWidget(backend_widget)
        self._layout = layout
        backend_name = "termqt" if isinstance(self._backend, TermQtBackend) else "fallback"
        terminal_widget = getattr(self._backend, "_terminal", None)
        self._logger.info(
            "terminal widget attached to tab backend=%s container=%s terminal=%s host=%s",
            backend_name,
            self._backend.widget().__class__.__name__,
            terminal_widget.__class__.__name__ if terminal_widget is not None else "n/a",
            self.host.name,
        )
        self._backend.widget().destroyed.connect(lambda: self.request_close("terminal_destroyed"))
        self._install_zoom_wheel_filter()

        if theme is not None:
            self.apply_theme(theme)
        else:
            self._apply_zoomed_font()

    def connect_session(self) -> bool:
        self.command_spec = build_ssh_command(self.host)
        argv = self._prepare_argv(self.command_spec.argv)
        keyfile = self._identity_file_from_argv(argv)
        if keyfile and not os.path.exists(keyfile):
            self._logger.error(
                "ssh identity file missing host=%s keyfile=%s", self.host.name, keyfile
            )
            self._switch_to_fallback(f"SSH key file not found: {keyfile}")
            self._session.set_error("identity_missing")
            return False

        self._logger.info(
            "connect_session host=%s target=%s user=%s port=%s command=%s",
            self.host.name,
            self.command_spec.target,
            self.command_spec.user,
            self.command_spec.port,
            shlex.join(argv),
        )
        started = self._session.start(argv)
        if not started and isinstance(self._backend, TermQtBackend):
            self._logger.error(
                "termqt spawn failed for host=%s; switching to fallback", self.host.name
            )
            self._switch_to_fallback(
                "Terminal startup failed. See ~/.cache/shelldeck/shelldeck.log"
            )
        if started:
            target = getattr(self._backend, "_terminal", None) or self._backend.widget()
            if hasattr(target, "setFocus"):
                try:
                    target.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
                except TypeError:
                    target.setFocus()
                except Exception:
                    self._logger.debug("setFocus failed on terminal target", exc_info=True)
        if not started:
            self._session.set_error("start_failed")
        return started

    def disconnect_session(self) -> None:
        self.request_close("user_disconnect")

    def reconnect_session(self) -> bool:
        if self._session.is_alive():
            self._pending_reconnect = True
            self.request_close("reconnect")
            return True
        return self.connect_session()

    def request_close(self, reason: str) -> None:
        self._session.request_close(reason)

    def force_kill(self, reason: str) -> None:
        self._session.force_kill(reason)

    def is_alive(self) -> bool:
        return self._session.is_alive()

    def clear_terminal(self) -> None:
        self._backend.clear()

    def session_state(self) -> SessionState:
        return self._session.state

    def zoom_in(self) -> None:
        self._adjust_zoom(1)

    def zoom_out(self) -> None:
        self._adjust_zoom(-1)

    def reset_zoom(self) -> None:
        self._set_zoom(self._base_zoom_size, mode=self._base_zoom_mode)

    def request_backend_sync(self, *, immediate: bool = False) -> None:
        request_sync = getattr(self._backend, "request_sync", None)
        if callable(request_sync):
            request_sync(immediate=immediate, reason="explicit")

    def set_terminal_resize_suspended(self, suspended: bool) -> None:
        set_resize_suspended = getattr(self._backend, "set_resize_suspended", None)
        if callable(set_resize_suspended):
            set_resize_suspended(suspended)

    def apply_theme(self, theme: ThemeConfig) -> None:
        self._backend.apply_theme(_build_terminal_theme(theme))
        self._apply_zoomed_font()

    def _init_session_controller(self) -> SessionController:
        session = SessionController(self._backend, self.host.name, self)
        session.state_changed.connect(self.state_changed.emit)
        session.closed.connect(self._on_session_closed)
        return session

    def _on_session_closed(self, reason: str) -> None:
        if self._pending_reconnect:
            self._pending_reconnect = False
            started = self.connect_session()
            if not started:
                self._logger.error("reconnect failed host=%s", self.host.name)
        self._logger.info(
            "session closed host=%s reason=%s",
            self.host.name,
            reason,
        )
        self.session_closed.emit(reason)

    def _switch_to_fallback(self, message: str) -> None:
        old_widget = self._backend.widget()
        self._layout.removeWidget(old_widget)
        old_widget.setParent(None)
        self._backend = FallbackBackend(self, message=message)
        old_session = self._session
        self._session = self._init_session_controller()
        old_session.deleteLater()
        new_widget = self._backend.widget()
        new_widget.destroyed.connect(lambda: self.request_close("terminal_destroyed"))
        new_widget.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self._layout.addWidget(new_widget)
        self._install_zoom_wheel_filter()
        self._set_zoom_property(self._zoom_size, self._zoom_mode)
        self._apply_font_size(self._zoom_size, self._zoom_mode)
        self._logger.info(
            "terminal widget attached to tab backend=fallback container=%s terminal=n/a host=%s",
            self._backend.widget().__class__.__name__,
            self.host.name,
        )
        old_widget.deleteLater()

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched in self._zoom_filter_targets() and event.type() == QtCore.QEvent.Type.Wheel:
            wheel_event = event if isinstance(event, QtGui.QWheelEvent) else None
            if wheel_event is not None and self._handle_ctrl_wheel_zoom(wheel_event):
                return True
        return super().eventFilter(watched, event)

    def _prepare_argv(self, argv: list[str]) -> list[str]:
        prepared = list(argv)
        if os.environ.get("SHELLDECK_SSH_DEBUG", "").strip() == "1":
            if "-vvv" not in prepared:
                insert_at = 1 if prepared and prepared[0] == "ssh" else 0
                prepared.insert(insert_at, "-vvv")
            self._logger.info("SHELLDECK_SSH_DEBUG=1 active; enabling ssh -vvv")
        return prepared

    def _identity_file_from_argv(self, argv: list[str]) -> str | None:
        for index, token in enumerate(argv):
            if token == "-i" and index + 1 < len(argv):
                return os.path.expanduser(argv[index + 1])
            if token.startswith("-i") and len(token) > 2:
                return os.path.expanduser(token[2:])
        return None

    def _install_zoom_wheel_filter(self) -> None:
        for target in self._zoom_filter_targets():
            install_filter = getattr(target, "installEventFilter", None)
            if callable(install_filter):
                install_filter(self)

    def _zoom_filter_targets(self) -> list[object]:
        targets: list[object] = [self._backend.widget()]
        terminal = getattr(self._backend, "_terminal", None)
        if terminal is not None and terminal is not targets[0]:
            targets.append(terminal)
        return targets

    def _handle_ctrl_wheel_zoom(self, event: QtGui.QWheelEvent) -> bool:
        modifiers = event.modifiers()
        if not bool(modifiers & QtCore.Qt.KeyboardModifier.ControlModifier):
            return False
        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.pixelDelta().y()
        if delta == 0:
            return False
        steps = int(delta / 120)
        if steps == 0:
            steps = 1 if delta > 0 else -1
        self._adjust_zoom(steps)
        event.accept()
        return True

    def _resolve_base_font(self) -> QtGui.QFont:
        target = self._zoom_target()
        widget_font = _get_terminal_font(target)
        if widget_font.pointSize() > 0 or widget_font.pixelSize() > 0:
            return widget_font
        fallback = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
        if fallback.pointSize() <= 0:
            fallback.setPointSize(DEFAULT_PT)
        return fallback

    def _adjust_zoom(self, delta: int) -> None:
        self._set_zoom(self._zoom_size + delta)

    def _set_zoom(self, size: int, *, mode: str | None = None) -> None:
        mode = mode or self._zoom_mode
        size = self._clamp_zoom(size)
        self._zoom_size = size
        self._zoom_mode = mode
        self._set_zoom_property(size, mode)
        self._apply_font_size(size, mode)

    def _apply_zoomed_font(self) -> None:
        size, mode = self._zoom_from_property()
        self._set_zoom(size, mode=mode)

    def _clamp_zoom(self, size: int) -> int:
        try:
            size = int(size)
        except (TypeError, ValueError):
            size = self._zoom_size
        return max(MIN_PT, min(MAX_PT, size))

    def _zoom_target(self) -> object:
        return getattr(self._backend, "_terminal", None) or self._backend.widget()

    def _zoom_from_property(self) -> tuple[int, str]:
        target = self._zoom_target()
        property_fn = getattr(target, "property", None)
        if not callable(property_fn):
            return self._zoom_size, self._zoom_mode
        value = property_fn("zoom_size")
        mode = property_fn("zoom_mode")
        if isinstance(value, (int, float)):
            value = int(value)
            if value > 0:
                zoom_mode = (
                    mode if isinstance(mode, str) and mode in {"pt", "px"} else self._zoom_mode
                )
                return value, zoom_mode
        return self._zoom_size, self._zoom_mode

    def _set_zoom_property(self, size: int, mode: str) -> None:
        target = self._zoom_target()
        set_property_fn = getattr(target, "setProperty", None)
        if not callable(set_property_fn):
            return
        set_property_fn("zoom_size", size)
        set_property_fn("zoom_mode", mode)

    def _apply_font_size(self, size: int, mode: str) -> None:
        font = QtGui.QFont(self._base_font)
        _set_font_size(font, size, mode)
        target = self._zoom_target()
        _set_terminal_font(target, font)
        self.request_backend_sync(immediate=True)
        self._force_terminal_refresh(target)

    def _force_terminal_refresh(self, target: object) -> None:
        repaint_signal = getattr(target, "total_repaint_sig", None)
        emit = getattr(repaint_signal, "emit", None)
        if callable(emit):
            emit()
        elif callable(getattr(target, "_canvas_repaint", None)):
            target._canvas_repaint()  # type: ignore[attr-defined]
        resize_fn = getattr(target, "resize", None)
        width_fn = getattr(target, "width", None)
        height_fn = getattr(target, "height", None)
        if callable(resize_fn) and callable(width_fn) and callable(height_fn):
            try:
                resize_fn(width_fn(), height_fn())
            except Exception:
                self._logger.debug("resize refresh failed", exc_info=True)
        update_fn = getattr(target, "update", None)
        if callable(update_fn):
            update_fn()
        repaint_fn = getattr(target, "repaint", None)
        if callable(repaint_fn):
            repaint_fn()


def _get_terminal_font(term: object) -> QtGui.QFont:
    for name in ("getTerminalFont", "terminalFont"):
        getter = getattr(term, name, None)
        if callable(getter):
            try:
                font = getter()
            except Exception:
                continue
            if isinstance(font, QtGui.QFont):
                return font
    font_value = getattr(term, "font", None)
    if isinstance(font_value, QtGui.QFont):
        return QtGui.QFont(font_value)
    if callable(font_value):
        try:
            font_candidate = font_value()
        except Exception:
            font_candidate = QtGui.QFont()
    else:
        font_candidate = QtGui.QFont()
    if isinstance(font_candidate, QtGui.QFont):
        return font_candidate
    return QtGui.QFont()


def _set_terminal_font(term: object, font: QtGui.QFont) -> None:
    set_terminal_font = getattr(term, "setTerminalFont", None)
    if callable(set_terminal_font):
        set_terminal_font(font)
        return
    set_font = getattr(term, "set_font", None)
    if callable(set_font):
        size, _mode = _get_font_size(font)
        if hasattr(term, "font_size"):
            try:
                cast(Any, term).font_size = size
            except Exception:
                pass
        set_font(font)
        return
    set_font_legacy = getattr(term, "setFont", None)
    if callable(set_font_legacy):
        set_font_legacy(font)


def _get_font_size(font: QtGui.QFont) -> tuple[int, str]:
    point = font.pointSize()
    if point > 0:
        return max(MIN_PT, min(MAX_PT, int(point))), "pt"
    pixel = font.pixelSize()
    if pixel > 0:
        return max(MIN_PT, min(MAX_PT, int(pixel))), "px"
    return DEFAULT_PT, "pt"


def _set_font_size(font: QtGui.QFont, new_size: int, mode: str) -> None:
    clamped = max(MIN_PT, min(MAX_PT, int(new_size)))
    if mode == "px":
        font.setPixelSize(clamped)
        return
    font.setPointSize(clamped)


def _build_terminal_theme(theme: ThemeConfig) -> TerminalTheme:
    accent = QtGui.QColor(theme.accent)
    if theme.mode == "light":
        background = QtGui.QColor("#ffffff")
        foreground = QtGui.QColor("#0f172a")
        border = QtGui.QColor("#e2e8f0")
    else:
        background = QtGui.QColor("#0f172a")
        foreground = QtGui.QColor("#e2e8f0")
        border = QtGui.QColor("#1f2937")
    selection = QtGui.QColor(accent)
    selection.setAlpha(80)
    cursor = QtGui.QColor(accent)
    return TerminalTheme(
        mode=theme.mode,
        background=background,
        foreground=foreground,
        accent=accent,
        selection=selection,
        cursor=cursor,
        border=border,
    )
