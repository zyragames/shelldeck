from __future__ import annotations

from dataclasses import dataclass
import sqlite3


@dataclass(frozen=True)
class Group:
    id: int
    name: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Group":
        return cls(id=int(row["id"]), name=str(row["name"]))


@dataclass(frozen=True)
class Host:
    id: int
    group_id: int
    name: str
    hostname: str
    port: int | None
    user: str | None
    identity_file: str | None
    ssh_config_host_alias: str | None
    notes: str | None
    tags: list[str]
    favorite: bool = False
    color: str | None = None
    tag: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row, tags: list[str] | None = None) -> "Host":
        return cls(
            id=int(row["id"]),
            group_id=int(row["group_id"]),
            name=str(row["name"]),
            hostname=str(row["hostname"]),
            port=int(row["port"]) if row["port"] is not None else None,
            user=str(row["user"]) if row["user"] is not None else None,
            identity_file=str(row["identity_file"]) if row["identity_file"] is not None else None,
            ssh_config_host_alias=(
                str(row["ssh_config_host_alias"])
                if row["ssh_config_host_alias"] is not None
                else None
            ),
            notes=str(row["notes"]) if row["notes"] is not None else None,
            tags=tags or [],
            favorite=bool(row["favorite"]) if "favorite" in row.keys() else False,
            color=str(row["color"]) if row["color"] is not None else None,
            tag=str(row["tag"]) if row["tag"] is not None else None,
        )
