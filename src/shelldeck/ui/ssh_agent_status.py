from __future__ import annotations

import logging
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from PySide6 import QtCore


class AgentState(Enum):
    OFF = "off"
    OK_KEYS = "ok_keys"
    OK_NO_KEYS = "ok_no_keys"
    ERROR = "error"


@dataclass(frozen=True)
class KeyInfo:
    fingerprint: str
    comment: str | None = None


@dataclass(frozen=True)
class StatusSnapshot:
    use_agent_enabled: bool
    ssh_auth_sock: str | None
    socket_exists: bool
    socket_is_socket: bool
    agent_reachable: bool
    keys_loaded: int | None
    keys: tuple[KeyInfo, ...]
    last_checked: datetime
    last_error: str | None
    state: AgentState
    detected_while_off: bool


_FINGERPRINT_RE = re.compile(r"(SHA256:[A-Za-z0-9+/=]+|MD5:[0-9a-f:]+)")


class SshAgentStatus(QtCore.QObject):
    status_changed = QtCore.Signal(object)

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._logger = logging.getLogger(__name__)
        self._use_agent_enabled = True
        self._process: QtCore.QProcess | None = None
        self._request_id = 0
        self._active_request_id: int | None = None
        self._last_state: AgentState | None = None
        self._last_error_logged: str | None = None
        self._last_snapshot: StatusSnapshot | None = None

    def set_use_agent_enabled(self, enabled: bool) -> None:
        self._use_agent_enabled = enabled

    def use_agent_enabled(self) -> bool:
        return self._use_agent_enabled

    def last_snapshot(self) -> StatusSnapshot | None:
        return self._last_snapshot

    def refresh(self) -> None:
        self._request_id += 1
        request_id = self._request_id
        self._active_request_id = request_id

        ssh_auth_sock = os.environ.get("SSH_AUTH_SOCK")
        socket_exists = False
        socket_is_socket = False
        last_error: str | None = None

        if ssh_auth_sock:
            socket_exists = os.path.exists(ssh_auth_sock)
            if socket_exists:
                try:
                    socket_is_socket = stat.S_ISSOCK(os.stat(ssh_auth_sock).st_mode)
                except OSError as exc:
                    socket_is_socket = False
                    last_error = f"SSH_AUTH_SOCK stat failed: {exc}"
            else:
                last_error = "SSH_AUTH_SOCK path missing"
        else:
            last_error = "SSH_AUTH_SOCK not set"

        if not ssh_auth_sock or not socket_exists or not socket_is_socket:
            snapshot = self._build_snapshot(
                ssh_auth_sock=ssh_auth_sock,
                socket_exists=socket_exists,
                socket_is_socket=socket_is_socket,
                agent_reachable=False,
                keys_loaded=None,
                keys=(),
                last_error=last_error,
            )
            self._emit_snapshot(snapshot)
            return

        if (
            self._process is not None
            and self._process.state() != QtCore.QProcess.ProcessState.NotRunning
        ):
            self._process.kill()

        process = QtCore.QProcess(self)
        self._process = process
        process.finished.connect(
            lambda exit_code, exit_status, rid=request_id: self._handle_finished(
                rid, exit_code, exit_status
            )
        )
        process.errorOccurred.connect(lambda error, rid=request_id: self._handle_error(rid, error))
        env = QtCore.QProcessEnvironment.systemEnvironment()
        env.insert("SSH_AUTH_SOCK", ssh_auth_sock)
        process.setProcessEnvironment(env)
        process.start("ssh-add", ["-l"])

    def _handle_error(self, request_id: int, error: QtCore.QProcess.ProcessError) -> None:
        if request_id != self._active_request_id:
            return
        process = self._process
        last_error = process.errorString() if process is not None else str(error)
        snapshot = self._build_snapshot(
            ssh_auth_sock=os.environ.get("SSH_AUTH_SOCK"),
            socket_exists=False,
            socket_is_socket=False,
            agent_reachable=False,
            keys_loaded=None,
            keys=(),
            last_error=last_error,
        )
        self._active_request_id = None
        self._emit_snapshot(snapshot)

    def _handle_finished(
        self,
        request_id: int,
        exit_code: int,
        exit_status: QtCore.QProcess.ExitStatus,
    ) -> None:
        if request_id != self._active_request_id:
            return

        process = self._process
        stdout = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        stderr = bytes(process.readAllStandardError()).decode("utf-8", errors="replace")
        output = "\n".join([stdout.strip(), stderr.strip()]).strip()

        agent_reachable = False
        keys_loaded: int | None = None
        keys: tuple[KeyInfo, ...] = ()
        last_error: str | None = None

        if exit_status != QtCore.QProcess.ExitStatus.NormalExit:
            last_error = "ssh-add exited abnormally"
        elif exit_code == 0:
            parsed_keys = self._parse_keys(output)
            keys = tuple(parsed_keys)
            keys_loaded = len(parsed_keys)
            agent_reachable = True
        elif exit_code == 1:
            lowered = output.lower()
            if "no identities" in lowered:
                agent_reachable = True
                keys_loaded = 0
            elif "could not open a connection" in lowered:
                last_error = output or "ssh-add could not reach agent"
            else:
                last_error = output or "ssh-add failed"
        else:
            last_error = output or f"ssh-add exit code {exit_code}"

        snapshot = self._build_snapshot(
            ssh_auth_sock=os.environ.get("SSH_AUTH_SOCK"),
            socket_exists=True,
            socket_is_socket=True,
            agent_reachable=agent_reachable,
            keys_loaded=keys_loaded,
            keys=keys,
            last_error=last_error,
        )
        self._active_request_id = None
        self._emit_snapshot(snapshot)

    def _parse_keys(self, output: str) -> list[KeyInfo]:
        keys: list[KeyInfo] = []
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            match = _FINGERPRINT_RE.search(stripped)
            if not match:
                continue
            fingerprint = match.group(1)
            comment = stripped[match.end() :].strip() or None
            keys.append(KeyInfo(fingerprint=fingerprint, comment=comment))
        return keys

    def _build_snapshot(
        self,
        *,
        ssh_auth_sock: str | None,
        socket_exists: bool,
        socket_is_socket: bool,
        agent_reachable: bool,
        keys_loaded: int | None,
        keys: tuple[KeyInfo, ...],
        last_error: str | None,
    ) -> StatusSnapshot:
        if not self._use_agent_enabled:
            state = AgentState.OFF
        elif agent_reachable:
            state = AgentState.OK_KEYS if (keys_loaded or 0) > 0 else AgentState.OK_NO_KEYS
        else:
            state = AgentState.ERROR

        detected_while_off = not self._use_agent_enabled and agent_reachable

        return StatusSnapshot(
            use_agent_enabled=self._use_agent_enabled,
            ssh_auth_sock=ssh_auth_sock,
            socket_exists=socket_exists,
            socket_is_socket=socket_is_socket,
            agent_reachable=agent_reachable,
            keys_loaded=keys_loaded,
            keys=keys,
            last_checked=datetime.now(),
            last_error=last_error,
            state=state,
            detected_while_off=detected_while_off,
        )

    def _emit_snapshot(self, snapshot: StatusSnapshot) -> None:
        if snapshot.state != self._last_state:
            self._logger.info(
                "ssh agent status transition prev=%s next=%s",
                self._last_state,
                snapshot.state,
            )
            self._last_state = snapshot.state

        if snapshot.last_error and snapshot.last_error != self._last_error_logged:
            self._logger.warning("ssh agent check failed error=%s", snapshot.last_error)
            self._last_error_logged = snapshot.last_error

        self._last_snapshot = snapshot
        self.status_changed.emit(snapshot)
