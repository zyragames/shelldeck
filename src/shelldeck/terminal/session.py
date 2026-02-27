from __future__ import annotations

from enum import Enum
import logging

from PySide6 import QtCore

from .backend import TerminalBackend


class SessionState(str, Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    CLOSING = "closing"
    CLOSED = "closed"
    ERROR = "error"


class SessionController(QtCore.QObject):
    state_changed = QtCore.Signal(str)
    closed = QtCore.Signal(str)

    def __init__(
        self,
        backend: TerminalBackend,
        label: str,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._logger = logging.getLogger(__name__)
        self._backend = backend
        self._label = label
        self._state = SessionState.CLOSED
        self._close_reason: str | None = None
        self._grace_timer = QtCore.QTimer(self)
        self._grace_timer.setSingleShot(True)
        self._grace_timer.timeout.connect(self._on_grace_timeout)
        self._kill_timer = QtCore.QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(self._on_kill_timeout)
        self._backend.process_exited.connect(self._on_process_exited)

    @property
    def state(self) -> SessionState:
        return self._state

    def start(
        self,
        argv: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> bool:
        if self._state in {SessionState.CONNECTING, SessionState.CONNECTED}:
            self._logger.warning(
                "session start ignored; already active host=%s state=%s",
                self._label,
                self._state.value,
            )
            return False
        self._set_state(SessionState.CONNECTING, reason="start")
        started = self._backend.start_process(argv, env=env, cwd=cwd)
        if started:
            self._set_state(SessionState.CONNECTED, reason="start_success")
            return True
        self._set_state(SessionState.ERROR, reason="start_failed")
        return False

    def request_close(self, reason: str) -> None:
        if self._state in {SessionState.CLOSING, SessionState.CLOSED}:
            self._logger.info(
                "session close ignored; already closing host=%s state=%s reason=%s",
                self._label,
                self._state.value,
                reason,
            )
            return
        self._close_reason = reason
        self._logger.info("session close requested host=%s reason=%s", self._label, reason)
        self._backend.detach_ui()
        self._backend.request_exit()
        self._set_state(SessionState.CLOSING, reason=reason)
        if self._backend.is_alive():
            self._grace_timer.start(800)
        else:
            self._finalize_closed("no_process")

    def force_kill(self, reason: str) -> None:
        if self._state == SessionState.CLOSED:
            return
        self._close_reason = reason
        self._logger.warning("session force kill host=%s reason=%s", self._label, reason)
        self._backend.detach_ui()
        self._backend.force_kill()
        self._set_state(SessionState.CLOSING, reason=reason)
        QtCore.QTimer.singleShot(150, lambda: self._finalize_closed("force_kill"))

    def is_alive(self) -> bool:
        if self._state in {SessionState.CLOSING, SessionState.CLOSED, SessionState.ERROR}:
            return self._backend.is_alive()
        return True

    def set_error(self, reason: str) -> None:
        self._set_state(SessionState.ERROR, reason=reason)

    def _on_grace_timeout(self) -> None:
        if not self._backend.is_alive():
            self._finalize_closed("grace_complete")
            return
        self._logger.warning("session terminate after grace host=%s", self._label)
        self._backend.terminate_process()
        self._kill_timer.start(700)

    def _on_kill_timeout(self) -> None:
        if not self._backend.is_alive():
            self._finalize_closed("terminated")
            return
        self._logger.error("session force kill after timeout host=%s", self._label)
        self._backend.force_kill()
        QtCore.QTimer.singleShot(150, lambda: self._finalize_closed("force_timeout"))

    def _on_process_exited(self, exit_code: object) -> None:
        if self._state == SessionState.CLOSED:
            return
        reason = self._close_reason or "process_exited"
        if self._state != SessionState.CLOSING:
            self._logger.warning(
                "session process exited host=%s exit_code=%s state=%s",
                self._label,
                exit_code,
                self._state.value,
            )
        else:
            self._logger.info(
                "session process exited host=%s exit_code=%s",
                self._label,
                exit_code,
            )
        self._finalize_closed(reason)

    def _finalize_closed(self, reason: str) -> None:
        if self._state == SessionState.CLOSED:
            return
        self._grace_timer.stop()
        self._kill_timer.stop()
        self._set_state(SessionState.CLOSED, reason=reason)
        self.closed.emit(reason)

    def _set_state(self, state: SessionState, reason: str) -> None:
        if self._state == state:
            return
        previous = self._state
        self._state = state
        level = logging.ERROR if state == SessionState.ERROR else logging.INFO
        self._logger.log(
            level,
            "session state transition host=%s from=%s to=%s reason=%s",
            self._label,
            previous.value,
            state.value,
            reason,
        )
        self.state_changed.emit(state.value)
