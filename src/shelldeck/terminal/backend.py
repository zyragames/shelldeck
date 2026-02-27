from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import shlex
import sys
import time
from typing import Any, Callable

try:
    from qtpy import QtCore, QtGui, QtWidgets
except Exception:  # pragma: no cover - fallback only when qtpy missing
    from PySide6 import QtCore, QtGui, QtWidgets


@dataclass(frozen=True)
class TerminalProcessConfig:
    argv: list[str]
    env: dict[str, str] | None = None
    cwd: str | None = None


@dataclass(frozen=True)
class TerminalTheme:
    mode: str
    background: QtGui.QColor
    foreground: QtGui.QColor
    accent: QtGui.QColor
    selection: QtGui.QColor
    cursor: QtGui.QColor
    border: QtGui.QColor


class TermQtRelay(QtCore.QObject):
    data = QtCore.Signal(object)  # type: ignore[attr-defined]

    def __init__(
        self,
        backend: "TermQtBackend",
        terminal: Any,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._backend = backend
        self._terminal = terminal
        self._update_pending = False

    @QtCore.Slot(object)  # type: ignore[attr-defined]
    def on_data(self, chunk: object) -> None:
        try:
            self._terminal.stdout(chunk)
        except Exception:
            return
        if _chunk_contains_clear_sequence(chunk):
            self._backend.request_sync()
        if not self._update_pending:
            self._update_pending = True
            QtCore.QTimer.singleShot(0, self._flush_update)

    def _flush_update(self) -> None:
        self._update_pending = False
        update_fn = getattr(self._terminal, "update", None)
        if callable(update_fn):
            try:
                update_fn()
            except Exception:
                return


class TerminalBackend(QtCore.QObject):
    process_exited = QtCore.Signal(object)  # type: ignore[attr-defined]

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._widget = self.create_terminal_widget(parent)

    def create_terminal_widget(self, parent: QtWidgets.QWidget | None) -> QtWidgets.QWidget:
        raise NotImplementedError

    def widget(self) -> QtWidgets.QWidget:
        return self._widget

    def start_process(
        self,
        argv: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> bool:
        raise NotImplementedError

    def write(self, data: bytes) -> None:
        return

    def request_exit(self) -> None:
        try:
            self.write(b"exit\n")
        except Exception:
            return

    def detach_ui(self) -> None:
        return

    def terminate_process(self) -> None:
        self.close()

    def force_kill(self) -> None:
        return

    def is_alive(self) -> bool:
        return False

    def close(self) -> None:
        return

    def clear(self) -> None:
        return

    def set_resize_suspended(self, suspended: bool) -> None:
        return

    def apply_theme(self, theme: TerminalTheme) -> None:
        widget = self._widget
        palette = widget.palette()
        palette.setColor(QtGui.QPalette.ColorRole.Base, theme.background)
        palette.setColor(QtGui.QPalette.ColorRole.Window, theme.background)
        palette.setColor(QtGui.QPalette.ColorRole.Text, theme.foreground)
        palette.setColor(QtGui.QPalette.ColorRole.WindowText, theme.foreground)
        palette.setColor(QtGui.QPalette.ColorRole.Highlight, theme.selection)
        palette.setColor(QtGui.QPalette.ColorRole.HighlightedText, theme.foreground)
        widget.setPalette(palette)
        widget.setStyleSheet(
            "background: {bg}; color: {fg}; selection-background-color: {sel}; "
            "selection-color: {fg}; border: 1px solid {border};".format(
                bg=theme.background.name(),
                fg=theme.foreground.name(),
                sel=theme.selection.name(),
                border=theme.border.name(),
            )
        )


class FallbackBackend(TerminalBackend):
    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
        message: str | None = None,
    ) -> None:
        self._message = message or (
            "Terminal backend unavailable (termqt not installed). "
            "Install termqt or use packaged release."
        )
        super().__init__(parent)
        self._set_message()

    def create_terminal_widget(self, parent: QtWidgets.QWidget | None) -> QtWidgets.QWidget:
        view = QtWidgets.QPlainTextEdit(parent)
        view.setReadOnly(True)
        view.setUndoRedoEnabled(False)
        view.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(11)
        view.setFont(font)
        return view

    def start_process(
        self,
        argv: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> bool:
        return False

    def clear(self) -> None:
        self._set_message()

    def _set_message(self) -> None:
        view = self.widget()
        if isinstance(view, QtWidgets.QPlainTextEdit):
            view.setPlainText(self._message)


class TermQtBackend(TerminalBackend):
    RESIZE_DEBOUNCE_MS = 120
    GENERIC_DEBOUNCE_MS = 50

    def __init__(self, termqt: Any, parent: QtWidgets.QWidget | None = None) -> None:
        self._termqt = termqt
        self._process: Any | None = None
        self._io: Any | None = None
        self._terminal: Any | None = None
        self._container: QtWidgets.QWidget | None = None
        self._stdout_relay: TermQtRelay | None = None
        self._stdout_relay_logged = False
        self._process_terminated = True
        self._close_requested = False
        self._sync_pending = False
        self._sync_log_window_start = 0.0
        self._sync_log_count = 0
        self._sync_features_logged = False
        self._sync_in_progress = False
        self._resize_suspended = False
        self._resize_pending = False
        super().__init__(parent)
        self._sync_timer = QtCore.QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.timeout.connect(self._flush_sync)
        self._log_sync_features_once()

    def create_terminal_widget(self, parent: QtWidgets.QWidget | None) -> QtWidgets.QWidget:
        widget = _create_termqt_widget(self._termqt, parent)
        if widget is None:
            raise RuntimeError("termqt widget not found")
        self._terminal = _extract_termqt_terminal(widget)
        self._container = widget
        self._container.installEventFilter(self)
        return widget

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched is self._container and event.type() == QtCore.QEvent.Type.Resize:
            if self._resize_suspended:
                self._resize_pending = True
                return False
            self.request_sync(reason="resize")
        return super().eventFilter(watched, event)

    def set_resize_suspended(self, suspended: bool) -> None:
        if suspended:
            self._resize_suspended = True
            return
        was_pending = self._resize_pending
        self._resize_suspended = False
        self._resize_pending = False
        if was_pending:
            self.request_sync(immediate=True, reason="splitter_release")

    def request_sync(self, *, immediate: bool = False, reason: str = "") -> None:
        if immediate:
            if self._sync_timer.isActive():
                self._sync_timer.stop()
            if self._sync_in_progress:
                self._sync_pending = True
                return
            self._flush_sync()
            return
        delay = self.RESIZE_DEBOUNCE_MS if reason == "resize" else self.GENERIC_DEBOUNCE_MS
        self._sync_timer.start(delay)

    def _flush_sync(self) -> None:
        if self._sync_in_progress:
            self._sync_pending = True
            return
        self._sync_in_progress = True
        try:
            self._sync_terminal_geometry()
        finally:
            self._sync_in_progress = False
        if self._sync_pending:
            self._sync_pending = False
            QtCore.QTimer.singleShot(0, self._flush_sync)

    def _sync_terminal_geometry(self) -> None:
        logger = logging.getLogger(__name__)
        terminal = self._terminal
        container = self._container
        io_obj = self._io or self._process
        if terminal is None or container is None:
            return

        try:
            container.updateGeometry()
            layout = container.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()
        except Exception:
            logger.debug("termqt container layout sync failed", exc_info=True)

        try:
            width = max(1, int(container.width()))
            height = max(1, int(container.height()))
            resize_fn = getattr(terminal, "resize", None)
            if callable(resize_fn):
                resize_fn(width, height)
        except Exception:
            logger.debug("termqt resize refresh failed", exc_info=True)

        try:
            buffer_obj = getattr(terminal, "_buffer", None)
            col_len = int(getattr(terminal, "col_len", 0) or 0)
            offset = int(getattr(terminal, "_buffer_display_offset", 0) or 0)
            if isinstance(buffer_obj, (list, tuple)):
                buffer_len = len(buffer_obj)
            else:
                buffer_len = len(buffer_obj) if buffer_obj is not None else 0
            max_offset = max(buffer_len - col_len, 0)
            clamped_offset = min(max(offset, 0), max_offset)
            if hasattr(terminal, "_buffer_display_offset") and clamped_offset != offset:
                setattr(terminal, "_buffer_display_offset", clamped_offset)
                update_scroll_position = getattr(terminal, "update_scroll_position", None)
                if callable(update_scroll_position):
                    update_scroll_position()
        except Exception:
            logger.debug("termqt buffer offset clamp failed", exc_info=True)

        try:
            update_fn = getattr(terminal, "update", None)
            if callable(update_fn):
                update_fn()
            viewport_fn = getattr(terminal, "viewport", None)
            if callable(viewport_fn):
                viewport = viewport_fn()
                update_viewport = getattr(viewport, "update", None)
                if callable(update_viewport):
                    update_viewport()
        except Exception:
            logger.debug("termqt paint flush update failed", exc_info=True)

        try:
            cols = int(getattr(terminal, "row_len"))
            rows = int(getattr(terminal, "col_len"))
        except Exception:
            rows = 0
            cols = 0

        if io_obj is not None and rows > 0 and cols > 0 and hasattr(io_obj, "resize"):
            try:
                io_obj.resize(rows, cols)
            except Exception:
                logger.exception(
                    "termqt pty resize sync failed rows=%s cols=%s size=%sx%s",
                    rows,
                    cols,
                    container.width(),
                    container.height(),
                )

        self._log_sync_event(container, rows, cols)

    def _log_sync_features_once(self) -> None:
        if self._sync_features_logged or os.environ.get("SHELLDECK_DEBUG") != "1":
            return
        logging.getLogger(__name__).info(
            "termqt: resize-sync enabled; state-sync enabled; coalesced paint enabled"
        )
        self._sync_features_logged = True

    def _log_sync_event(self, container: QtWidgets.QWidget, rows: int, cols: int) -> None:
        if os.environ.get("SHELLDECK_DEBUG") != "1":
            return
        now = time.monotonic()
        if now - self._sync_log_window_start >= 1.0:
            self._sync_log_window_start = now
            self._sync_log_count = 0
        if self._sync_log_count >= 5:
            return
        self._sync_log_count += 1
        window = container.window() if hasattr(container, "window") else None
        maximized = bool(window is not None and window.isMaximized())
        logging.getLogger(__name__).debug(
            "termqt sync event maximized=%s container=%sx%s rows=%s cols=%s",
            maximized,
            container.width(),
            container.height(),
            rows,
            cols,
        )

    def start_process(
        self,
        argv: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> bool:
        config = TerminalProcessConfig(argv=argv, env=env, cwd=cwd)
        try:
            return _start_termqt_process(self, config)
        except Exception:
            logging.getLogger(__name__).exception(
                "termqt start_process failed; argv=%s",
                argv,
            )
            return False

    def write(self, data: bytes) -> None:
        target = self._process or self._terminal or self._widget
        for name in ("write", "write_data", "writeData"):
            if hasattr(target, name):
                try:
                    getattr(target, name)(data)
                except TypeError:
                    getattr(target, name)(data.decode(errors="replace"))
                return

    def close(self) -> None:
        self.terminate_process()

    def request_exit(self) -> None:
        logger = logging.getLogger(__name__)
        self.write(b"exit\n")
        target = self._process or self._terminal
        for name in ("close_stdin", "closeStdin", "closeInput", "close"):
            if hasattr(target, name):
                try:
                    getattr(target, name)()
                except Exception:
                    logger.debug("termqt close stdin failed via %s", name, exc_info=True)
                break

    def detach_ui(self) -> None:
        logger = logging.getLogger(__name__)
        if self._sync_timer.isActive():
            self._sync_timer.stop()
        self._sync_pending = False
        self._resize_pending = False
        container = self._container
        if container is not None:
            try:
                container.removeEventFilter(self)
            except Exception:
                logger.debug("termqt event filter detach failed", exc_info=True)
        relay = self._stdout_relay
        if relay is not None:
            try:
                relay.data.disconnect(relay.on_data)
            except Exception:
                logger.debug("termqt stdout relay disconnect failed", exc_info=True)
        terminal = self._terminal
        self._terminal = None
        self._container = None
        if terminal is not None:
            for name in ("stdin_callback", "resize_callback"):
                if hasattr(terminal, name):
                    try:
                        setattr(terminal, name, None)
                    except Exception:
                        logger.debug("termqt terminal detach failed for %s", name, exc_info=True)
        process = self._process
        if process is not None and hasattr(process, "stdout_callback"):
            try:
                setattr(process, "stdout_callback", lambda *_args, **_kwargs: None)
            except Exception:
                logger.debug("termqt stdout_callback detach failed", exc_info=True)
        self._stdout_relay = None

    def terminate_process(self) -> None:
        logger = logging.getLogger(__name__)
        target = self._process
        if target is None:
            return
        self._close_requested = True
        for name in ("terminate", "close"):
            if hasattr(target, name):
                try:
                    getattr(target, name)()
                    return
                except Exception:
                    logger.exception("termqt process terminate failed via %s", name)

    def force_kill(self) -> None:
        logger = logging.getLogger(__name__)
        target = self._process
        if target is None:
            return
        for name in ("kill", "terminate"):
            if hasattr(target, name):
                try:
                    getattr(target, name)()
                    return
                except Exception:
                    logger.exception("termqt process kill failed via %s", name)

    def is_alive(self) -> bool:
        process = self._process
        if process is None:
            return False
        state = _get_optional_attr(
            process,
            (
                "is_running",
                "isRunning",
                "running",
                "is_alive",
                "alive",
            ),
        )
        if isinstance(state, bool):
            return state
        return not self._process_terminated

    def _handle_process_terminated(self, exit_code: int | None) -> None:
        if self._process_terminated:
            return
        self._process_terminated = True
        self.process_exited.emit(exit_code)
        self._process = None
        self._io = None

    def clear(self) -> None:
        clear_fn = getattr(self._terminal or self._widget, "clear", None)
        if callable(clear_fn):
            try:
                clear_fn()
                self.request_sync()
            except Exception:
                return

    def apply_theme(self, theme: TerminalTheme) -> None:
        super().apply_theme(theme)
        widget = self._terminal or self._widget
        _apply_termqt_color(
            widget,
            theme.background,
            [
                "setBackgroundColor",
                "set_background_color",
                "setBackground",
            ],
        )
        _apply_termqt_color(
            widget,
            theme.foreground,
            [
                "setForegroundColor",
                "set_foreground_color",
                "setTextColor",
                "set_text_color",
            ],
        )
        _apply_termqt_color(
            widget,
            theme.selection,
            [
                "setSelectionColor",
                "set_selection_color",
                "setSelectionBackgroundColor",
            ],
        )
        _apply_termqt_color(
            widget,
            theme.cursor,
            [
                "setCursorColor",
                "set_cursor_color",
            ],
        )


def create_terminal_backend(parent: QtWidgets.QWidget | None = None) -> TerminalBackend:
    logger = logging.getLogger(__name__)
    backend_mode = os.environ.get("SHELLDECK_TERM_BACKEND", "auto").strip().lower() or "auto"
    if backend_mode not in {"auto", "termqt", "fallback"}:
        logger.warning("Unknown SHELLDECK_TERM_BACKEND=%s; using auto", backend_mode)
        backend_mode = "auto"

    if backend_mode == "fallback":
        logger.info("Terminal backend selected: fallback (forced by SHELLDECK_TERM_BACKEND)")
        return FallbackBackend(
            parent,
            message="Terminal backend forced to fallback by SHELLDECK_TERM_BACKEND=fallback.",
        )

    if os.environ.get("QT_API", "").strip() == "":
        os.environ["QT_API"] = "pyside6"
        logger.debug("QT_API not set, defaulting to pyside6")

    try:
        import termqt  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        if exc.name == "termqt":
            logger.info("termqt missing; using fallback. sys.executable=%s", sys.executable)
        else:
            logger.exception(
                "termqt dependency missing (%s); using fallback. sys.executable=%s",
                exc.name,
                sys.executable,
            )
        message = (
            "Terminal backend unavailable (termqt not installed). "
            "Install termqt or use packaged release."
            if exc.name == "termqt"
            else "Terminal backend unavailable (termqt failed to initialize). See logs."
        )
        if backend_mode == "termqt":
            logger.warning("Forced termqt backend could not be loaded; using fallback")
        return FallbackBackend(parent, message=message)
    except Exception:
        logger.exception(
            "termqt import failed; using fallback. sys.executable=%s",
            sys.executable,
        )
        if backend_mode == "termqt":
            logger.warning("Forced termqt backend import failed; using fallback")
        return FallbackBackend(
            parent,
            message="Terminal backend unavailable (termqt failed to initialize). See logs.",
        )

    try:
        import qtpy  # type: ignore[import-not-found]

        api_name = str(getattr(qtpy, "API_NAME", ""))
        if api_name and api_name.lower() != "pyside6":
            logger.warning("qtpy binding is %s (expected PySide6)", api_name)
            return FallbackBackend(
                parent,
                message=(
                    "Terminal backend unavailable (qtpy binding mismatch). "
                    "See ~/.cache/shelldeck/shelldeck.log"
                ),
            )
        else:
            logger.info("termqt qt binding active: qtpy.API_NAME=%s", api_name or "unknown")
    except Exception:
        logger.exception("qtpy unavailable; using fallback for termqt backend")
        if backend_mode == "termqt":
            logger.warning("Forced termqt backend missing qtpy; using fallback")
        return FallbackBackend(
            parent,
            message=(
                "Terminal backend unavailable (qtpy missing). Install qtpy with PySide6 support."
            ),
        )

    try:
        backend = TermQtBackend(termqt, parent)
    except Exception:
        logger.exception(
            "termqt backend init failed; using fallback. sys.executable=%s",
            sys.executable,
        )
        if backend_mode == "termqt":
            logger.warning("Forced termqt backend init failed; using fallback")
        return FallbackBackend(
            parent,
            message="Terminal backend unavailable (termqt failed to initialize). See logs.",
        )
    if backend_mode == "termqt":
        logger.info("Terminal backend selected: termqt (forced)")
    else:
        logger.info("Terminal backend selected: termqt")
    return backend


def _create_termqt_widget(
    termqt: Any,
    parent: QtWidgets.QWidget | None,
) -> QtWidgets.QWidget | None:
    logger = logging.getLogger(__name__)
    terminal_type = getattr(termqt, "Terminal", None)
    candidates = ("TerminalWidget", "TerminalView", "Terminal", "TerminalQtWidget")
    for name in candidates:
        widget_type = getattr(termqt, name, None)
        if widget_type is None:
            continue

        is_terminal = (
            widget_type is terminal_type
            or name == "Terminal"
            or getattr(widget_type, "__name__", "") == "Terminal"
        )
        if is_terminal:
            try:
                terminal = widget_type(800, 600, logger=logger)
            except Exception:
                logger.exception(
                    "termqt widget init failed for %s (expected ctor: Terminal(width, height, logger=...))",
                    name,
                )
                continue

            try:
                container = QtWidgets.QWidget(parent)
                container.setObjectName("terminalContainer")
                container.setSizePolicy(
                    QtWidgets.QSizePolicy.Policy.Expanding,
                    QtWidgets.QSizePolicy.Policy.Expanding,
                )
                container.setMinimumSize(1, 1)
                layout = QtWidgets.QHBoxLayout(container)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)
                try:
                    terminal.setObjectName("termqtTerminal")
                    terminal.setParent(container)
                    terminal.setSizePolicy(
                        QtWidgets.QSizePolicy.Policy.Expanding,
                        QtWidgets.QSizePolicy.Policy.Expanding,
                    )
                except Exception:
                    logger.debug("termqt terminal parenting flags not applied", exc_info=True)
                layout.addWidget(terminal)

                scroll = QtWidgets.QScrollBar(QtCore.Qt.Orientation.Vertical, container)
                layout.addWidget(scroll)

                connect_scroll_bar = getattr(terminal, "connect_scroll_bar", None)
                if callable(connect_scroll_bar):
                    connect_scroll_bar(scroll)

                set_font = getattr(terminal, "set_font", None)
                if callable(set_font):
                    set_font()

                try:
                    padding = int(getattr(terminal, "_padding", 4))
                    char_width = int(getattr(terminal, "char_width", 8))
                    line_height = int(getattr(terminal, "line_height", 16))
                    min_width = max(32, char_width + padding)
                    min_height = max(24, line_height + padding)
                    terminal.setMinimumSize(min_width, min_height)
                except Exception:
                    logger.debug("termqt minimum size setup failed", exc_info=True)

                try:
                    terminal.maximum_line_history = 2000
                except Exception:
                    logger.debug("termqt maximum_line_history not settable for %s", name)

                if os.environ.get("SHELLDECK_DEBUG") == "1":
                    try:
                        logger.info(
                            "termqt widget flags terminal=%s container=%s native=%s no_ancestors=%s",
                            int(terminal.windowFlags()),
                            int(container.windowFlags()),
                            terminal.testAttribute(QtCore.Qt.WidgetAttribute.WA_NativeWindow),
                            terminal.testAttribute(
                                QtCore.Qt.WidgetAttribute.WA_DontCreateNativeAncestors
                            ),
                        )
                    except Exception:
                        logger.debug("termqt widget flag logging failed", exc_info=True)

                setattr(container, "_shelldeck_termqt_terminal", terminal)
                return container
            except Exception:
                logger.exception("termqt widget setup failed for %s", name)
                continue

        try:
            widget = widget_type()
        except TypeError:
            if parent is None:
                logger.debug("termqt %s requires parent argument", name)
                continue
            try:
                widget = widget_type(parent)
            except Exception:
                logger.exception("termqt widget init failed for %s (parent ctor)", name)
                continue
        except Exception:
            logger.exception("termqt widget init failed for %s (no-arg ctor)", name)
            continue
        if isinstance(widget, QtWidgets.QWidget):
            return widget
        logger.debug("termqt %s did not return a QWidget", name)
    return None


def _start_termqt_process(backend: TermQtBackend, config: TerminalProcessConfig) -> bool:
    logger = logging.getLogger(__name__)
    widget = backend.widget()
    terminal = backend._terminal or _extract_termqt_terminal(widget)
    termqt = backend._termqt
    logger.info("termqt start requested argv=%s", config.argv)

    if terminal is None:
        logger.error("termqt terminal widget not found")
        return False

    if sys.platform.startswith("linux") and hasattr(terminal, "enable_auto_wrap"):
        try:
            terminal.enable_auto_wrap(True)
        except Exception:
            logger.debug("termqt enable_auto_wrap failed", exc_info=True)

    process_type = getattr(termqt, "TerminalPOSIXExecIO", None)
    if process_type is None:
        logger.error("termqt TerminalPOSIXExecIO not found")
        return False

    command = shlex.join(config.argv)
    try:
        logger.info(
            "termqt spawning pty cmd=%s rows=%s cols=%s",
            command,
            getattr(terminal, "row_len", "?"),
            getattr(terminal, "col_len", "?"),
        )
        terminal_io = process_type(terminal.row_len, terminal.col_len, command, logger=logger)
        relay = TermQtRelay(backend, terminal, backend)
        relay.data.connect(relay.on_data)
        terminal_io.stdout_callback = lambda chunk, _relay=relay: _relay.data.emit(chunk)
        terminal.stdin_callback = terminal_io.write

        def _safe_resize_callback(rows: int, cols: int, _io: Any = terminal_io) -> None:
            if rows <= 0 or cols <= 0:
                logger.debug("termqt resize ignored invalid rows=%s cols=%s", rows, cols)
                return
            _io.resize(rows, cols)

        terminal.resize_callback = _safe_resize_callback
        backend._stdout_relay = relay
        backend._io = terminal_io
        if not backend._stdout_relay_logged and os.environ.get("SHELLDECK_DEBUG") == "1":
            logger.info("termqt stdout relay enabled (coalesced updates)")
            backend._stdout_relay_logged = True
        _install_termination_logging(
            terminal_io,
            command,
            lambda exit_code, _backend=backend: _backend._handle_process_terminated(exit_code),
        )
        _apply_env_cwd(terminal_io, config.env, config.cwd)
        terminal_io.spawn()
    except Exception:
        logger.exception("termqt TerminalPOSIXExecIO spawn failed for cmd=%s", command)
        return False

    pid = _get_optional_attr(terminal_io, ("pid", "process_pid", "child_pid", "_pid"))
    fd = _get_optional_attr(terminal_io, ("fd", "pty_fd", "master_fd", "_fd"))
    logger.info("PTY spawn success cmd=%s pid=%s fd=%s", command, pid, fd)

    if hasattr(terminal, "update"):
        try:
            QtCore.QTimer.singleShot(0, terminal.update)
        except Exception:
            logger.debug("termqt update scheduling failed after spawn", exc_info=True)
    if hasattr(terminal, "setFocus"):
        try:
            terminal.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
        except TypeError:
            terminal.setFocus()
        except Exception:
            logger.debug("termqt setFocus failed after spawn", exc_info=True)

    backend._terminal = terminal
    backend._process = terminal_io
    backend._io = terminal_io
    backend._process_terminated = False
    backend._close_requested = False
    backend.request_sync()
    logger.info("termqt backend active, spawned pty for cmd=%s", command)
    return True


def _chunk_contains_clear_sequence(chunk: object) -> bool:
    if isinstance(chunk, bytes):
        return b"\x1b[2J" in chunk or b"\x1b[H" in chunk
    if isinstance(chunk, str):
        return "\x1b[2J" in chunk or "\x1b[H" in chunk
    return False


def _extract_termqt_terminal(widget: QtWidgets.QWidget) -> Any | None:
    terminal = getattr(widget, "_shelldeck_termqt_terminal", None)
    if terminal is not None:
        return terminal
    if all(hasattr(widget, attr) for attr in ("row_len", "col_len", "stdout")):
        return widget
    return None


def _get_optional_attr(target: Any, names: tuple[str, ...]) -> Any | None:
    for name in names:
        if not hasattr(target, name):
            continue
        value = getattr(target, name)
        if callable(value):
            try:
                value = value()
            except Exception:
                continue
        return value
    return None


def _install_termination_logging(
    process: Any,
    command: str,
    on_terminated: Callable[[int | None], None] | None = None,
) -> None:
    logger = logging.getLogger(__name__)
    if not hasattr(process, "terminated_callback"):
        return
    previous = getattr(process, "terminated_callback", None)

    def _on_terminated(*args: Any, **kwargs: Any) -> None:
        exit_code = kwargs.get("exit_code")
        if exit_code is None:
            for value in args:
                if isinstance(value, int):
                    exit_code = value
                    break
        logger.info("termqt process terminated cmd=%s exit_code=%s", command, exit_code)
        if on_terminated is not None:
            try:
                on_terminated(exit_code)
            except Exception:
                logger.exception("termqt termination hook failed for cmd=%s", command)
        if callable(previous):
            try:
                previous(*args, **kwargs)
            except Exception:
                logger.exception("termqt terminated callback failed for cmd=%s", command)

    try:
        setattr(process, "terminated_callback", _on_terminated)
    except Exception:
        logger.debug("termqt terminated_callback not assignable", exc_info=True)


def _resolve_start_target(
    widget: QtWidgets.QWidget, process: Any | None
) -> tuple[Any, Callable[..., Any] | None]:
    for name in ("start_process", "startProcess", "start"):
        if hasattr(widget, name):
            return widget, getattr(widget, name)
    if process is not None:
        for name in ("start_process", "startProcess", "start"):
            if hasattr(process, name):
                return process, getattr(process, name)
    return widget, None


def _invoke_start(start_fn: Callable[..., Any], argv: list[str]) -> bool:
    logger = logging.getLogger(__name__)
    program = argv[0] if argv else ""
    args = argv[1:]
    command = " ".join(argv)
    signatures = (
        ("start(program, args)", lambda: start_fn(program, args)),
        ("start(argv)", lambda: start_fn(argv)),
        ("start(program)", lambda: start_fn(program)),
        ("start(command)", lambda: start_fn(command)),
    )
    for signature, candidate in signatures:
        try:
            result = candidate()
        except TypeError:
            continue
        except Exception:
            logger.exception("termqt start call failed for %s", signature)
            return False
        logger.debug("termqt start call accepted signature %s", signature)
        if isinstance(result, bool):
            return result
        return True
    logger.error("termqt start call rejected all known signatures")
    return False


def _apply_env_cwd(target: Any, env: dict[str, str] | None, cwd: str | None) -> None:
    if env:
        if hasattr(target, "setEnvironment"):
            target.setEnvironment([f"{key}={value}" for key, value in env.items()])
        elif hasattr(target, "setProcessEnvironment"):
            process_env = QtCore.QProcessEnvironment()
            for key, value in env.items():
                process_env.insert(key, value)
            target.setProcessEnvironment(process_env)
    if cwd and hasattr(target, "setWorkingDirectory"):
        target.setWorkingDirectory(cwd)


def _attach_process(widget: QtWidgets.QWidget, process: Any) -> None:
    for name in ("setProcess", "set_process", "setTerminalProcess"):
        if hasattr(widget, name):
            try:
                getattr(widget, name)(process)
            except Exception:
                return


def _enable_pty(target: Any) -> None:
    for name in (
        "setPty",
        "set_pty",
        "setUsePty",
        "set_use_pty",
        "enablePty",
        "enable_pty",
    ):
        if hasattr(target, name):
            method = getattr(target, name)
            try:
                method(True)
            except TypeError:
                try:
                    method()
                except Exception:
                    return
            return


def _apply_termqt_color(target: Any, color: QtGui.QColor, names: list[str]) -> None:
    for name in names:
        if not hasattr(target, name):
            continue
        method = getattr(target, name)
        for value in (color, color.name()):
            try:
                method(value)
                return
            except TypeError:
                continue
            except Exception:
                return
