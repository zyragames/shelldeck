from __future__ import annotations

from dataclasses import dataclass
import os
import shlex
from typing import Callable

from ..data.models import Host
from ..ssh_config import load_ssh_config


@dataclass(frozen=True)
class SshConfigOptions:
    user: str | None
    port: int | None
    identity_file: str | None


@dataclass(frozen=True)
class SshCommandSpec:
    argv: list[str]
    display: str
    target: str
    user: str | None
    port: int | None
    identity_file: str | None
    ssh_config_host_alias: str | None


SshConfigResolver = Callable[[Host], SshConfigOptions]


def resolve_ssh_config(host: Host, config_path: str = "~/.ssh/config") -> SshConfigOptions:
    target = host.ssh_config_host_alias or host.hostname
    config = load_ssh_config(config_path)
    options = config.lookup(target) if target else {}
    user = str(options.get("user")) if options.get("user") else None
    port = _safe_int(options.get("port"))
    identity_file = _first_identity_file(options.get("identityfile"))
    return SshConfigOptions(user=user, port=port, identity_file=identity_file)


def build_ssh_argv(host: Host, ssh_config_resolver: SshConfigResolver | None) -> list[str]:
    if host.ssh_config_host_alias:
        return ["ssh", "-tt", host.ssh_config_host_alias]

    config = (
        ssh_config_resolver(host) if ssh_config_resolver else SshConfigOptions(None, None, None)
    )
    user = host.user or config.user
    port = host.port if host.port is not None else config.port
    identity_file = host.identity_file or config.identity_file

    argv: list[str] = ["ssh", "-tt"]
    if port:
        argv.extend(["-p", str(port)])
    if user:
        argv.extend(["-l", user])
    if identity_file:
        argv.extend(["-i", os.path.expanduser(identity_file)])
    argv.append(host.hostname)
    return argv


def build_ssh_command(host: Host, config_path: str = "~/.ssh/config") -> SshCommandSpec:
    resolver = lambda resolved_host: resolve_ssh_config(resolved_host, config_path)
    argv = build_ssh_argv(host, resolver)
    if host.ssh_config_host_alias:
        target = host.ssh_config_host_alias
        user = None
        port = None
        identity_file = None
    else:
        target = host.hostname
        resolved = resolve_ssh_config(host, config_path)
        user = host.user or resolved.user
        port = host.port if host.port is not None else resolved.port
        identity_file = host.identity_file or resolved.identity_file

    return SshCommandSpec(
        argv=argv,
        display=shlex.join(argv),
        target=target,
        user=user,
        port=port,
        identity_file=identity_file,
        ssh_config_host_alias=host.ssh_config_host_alias,
    )


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
