from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

import paramiko


@dataclass(frozen=True)
class SshConfigEntry:
    alias: str
    hostname: str
    user: str | None
    port: int | None
    identity_file: str | None
    proxy_jump: str | None


def load_ssh_config(path: str | Path) -> paramiko.SSHConfig:
    config_path = Path(path).expanduser()
    config = paramiko.SSHConfig()
    if not config_path.exists():
        return config
    with config_path.open("r", encoding="utf-8") as handle:
        config.parse(handle)
    return config


def list_ssh_config_entries(path: str | Path = "~/.ssh/config") -> list[SshConfigEntry]:
    config = load_ssh_config(path)
    entries: list[SshConfigEntry] = []
    for alias in sorted(config.get_hostnames()):
        if _is_pattern(alias):
            continue
        options = config.lookup(alias)
        hostname = str(options.get("hostname") or alias)
        user = str(options.get("user")) if options.get("user") else None
        port = _safe_int(options.get("port"))
        identity_file = _first_identity_file(options.get("identityfile"))
        proxy_jump = str(options.get("proxyjump")) if options.get("proxyjump") else None
        entries.append(
            SshConfigEntry(
                alias=alias,
                hostname=hostname,
                user=user,
                port=port,
                identity_file=identity_file,
                proxy_jump=proxy_jump,
            )
        )
    return entries


def _is_pattern(host: str) -> bool:
    return not host or "*" in host or "?" in host or host.startswith("!")


def _safe_int(value: object | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _first_identity_file(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        if not value:
            return None
        value = value[0]
    return os.path.expanduser(str(value))
