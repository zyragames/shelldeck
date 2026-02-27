from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from pathlib import Path

from .db import Database, get_default_db_path
from .models import Group, Host


@dataclass
class Repository:
    _db: Database

    @classmethod
    def open_default(cls) -> "Repository":
        return cls(Database.open(get_default_db_path()))

    @classmethod
    def open(cls, path: Path) -> "Repository":
        return cls(Database.open(path))

    def close(self) -> None:
        self._db.close()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._db.connection

    def list_groups(self) -> list[Group]:
        cursor = self.connection.execute("SELECT id, name FROM groups ORDER BY name")
        return [Group.from_row(row) for row in cursor.fetchall()]

    def get_group(self, group_id: int) -> Group | None:
        row = self.connection.execute(
            "SELECT id, name FROM groups WHERE id = ?", (group_id,)
        ).fetchone()
        return Group.from_row(row) if row else None

    def get_group_by_name(self, name: str) -> Group | None:
        row = self.connection.execute(
            "SELECT id, name FROM groups WHERE name = ?", (name,)
        ).fetchone()
        return Group.from_row(row) if row else None

    def get_or_create_group(self, name: str) -> Group:
        existing = self.get_group_by_name(name)
        if existing:
            return existing
        with self.connection:
            cursor = self.connection.execute("INSERT INTO groups (name) VALUES (?)", (name,))
        return Group(id=int(cursor.lastrowid), name=name)

    def create_group(self, name: str) -> Group:
        with self.connection:
            cursor = self.connection.execute("INSERT INTO groups (name) VALUES (?)", (name,))
        return Group(id=int(cursor.lastrowid), name=name)

    def update_group(self, group_id: int, name: str) -> None:
        with self.connection:
            self.connection.execute("UPDATE groups SET name = ? WHERE id = ?", (name, group_id))

    def delete_group(self, group_id: int) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM groups WHERE id = ?", (group_id,))

    def list_hosts_for_group(self, group_id: int) -> list[Host]:
        cursor = self.connection.execute(
            "SELECT * FROM hosts WHERE group_id = ? ORDER BY name", (group_id,)
        )
        rows = cursor.fetchall()
        tags_map = self._get_tags_for_hosts([int(row["id"]) for row in rows])
        return [Host.from_row(row, tags_map.get(int(row["id"]), [])) for row in rows]

    def list_groups_with_hosts(self) -> list[tuple[Group, list[Host]]]:
        groups = self.list_groups()
        if not groups:
            return []
        group_ids = [group.id for group in groups]
        placeholders = ",".join("?" for _ in group_ids)
        cursor = self.connection.execute(
            f"SELECT * FROM hosts WHERE group_id IN ({placeholders}) ORDER BY name",
            group_ids,
        )
        rows = cursor.fetchall()
        tags_map = self._get_tags_for_hosts([int(row["id"]) for row in rows])
        hosts_by_group: dict[int, list[Host]] = {group.id: [] for group in groups}
        for row in rows:
            host = Host.from_row(row, tags_map.get(int(row["id"]), []))
            hosts_by_group[host.group_id].append(host)
        return [(group, hosts_by_group.get(group.id, [])) for group in groups]

    def get_host(self, host_id: int) -> Host | None:
        row = self.connection.execute("SELECT * FROM hosts WHERE id = ?", (host_id,)).fetchone()
        if not row:
            return None
        tags_map = self._get_tags_for_hosts([int(row["id"])])
        return Host.from_row(row, tags_map.get(int(row["id"]), []))

    def find_host_for_merge(
        self, group_id: int, hostname: str | None, name: str | None
    ) -> Host | None:
        if hostname:
            row = self.connection.execute(
                "SELECT * FROM hosts WHERE group_id = ? AND hostname = ?",
                (group_id, hostname),
            ).fetchone()
            if row:
                tags_map = self._get_tags_for_hosts([int(row["id"])])
                return Host.from_row(row, tags_map.get(int(row["id"]), []))
        if name:
            row = self.connection.execute(
                "SELECT * FROM hosts WHERE group_id = ? AND name = ?",
                (group_id, name),
            ).fetchone()
            if row:
                tags_map = self._get_tags_for_hosts([int(row["id"])])
                return Host.from_row(row, tags_map.get(int(row["id"]), []))
        return None

    def create_host(self, host: Host) -> Host:
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO hosts
                    (group_id, name, hostname, port, user, identity_file, ssh_config_host_alias, notes,
                     favorite, color, tag)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    host.group_id,
                    host.name,
                    host.hostname,
                    host.port,
                    host.user,
                    host.identity_file,
                    host.ssh_config_host_alias,
                    host.notes,
                    1 if host.favorite else 0,
                    host.color,
                    host.tag,
                ),
            )
        created = Host(
            id=int(cursor.lastrowid),
            group_id=host.group_id,
            name=host.name,
            hostname=host.hostname,
            port=host.port,
            user=host.user,
            identity_file=host.identity_file,
            ssh_config_host_alias=host.ssh_config_host_alias,
            notes=host.notes,
            tags=host.tags,
            favorite=host.favorite,
            color=host.color,
            tag=host.tag,
        )
        self._set_host_tags(created.id, host.tags)
        return created

    def update_host(self, host: Host) -> None:
        with self.connection:
            self.connection.execute(
                """
                UPDATE hosts
                SET group_id = ?, name = ?, hostname = ?, port = ?, user = ?,
                    identity_file = ?, ssh_config_host_alias = ?, notes = ?,
                    favorite = ?, color = ?, tag = ?
                WHERE id = ?
                """,
                (
                    host.group_id,
                    host.name,
                    host.hostname,
                    host.port,
                    host.user,
                    host.identity_file,
                    host.ssh_config_host_alias,
                    host.notes,
                    1 if host.favorite else 0,
                    host.color,
                    host.tag,
                    host.id,
                ),
            )
        self._set_host_tags(host.id, host.tags)

    def delete_host(self, host_id: int) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM hosts WHERE id = ?", (host_id,))

    def _get_tags_for_hosts(self, host_ids: list[int]) -> dict[int, list[str]]:
        if not host_ids:
            return {}
        placeholders = ",".join("?" for _ in host_ids)
        cursor = self.connection.execute(
            f"""
            SELECT ht.host_id, t.name
            FROM host_tags ht
            JOIN tags t ON t.id = ht.tag_id
            WHERE ht.host_id IN ({placeholders})
            ORDER BY t.name
            """,
            host_ids,
        )
        tags_map: dict[int, list[str]] = {host_id: [] for host_id in host_ids}
        for row in cursor.fetchall():
            tags_map[int(row["host_id"])].append(str(row["name"]))
        return tags_map

    def _ensure_tags(self, tags: list[str]) -> dict[str, int]:
        if not tags:
            return {}
        normalized = [tag.strip() for tag in tags if tag.strip()]
        if not normalized:
            return {}
        placeholders = ",".join("?" for _ in normalized)
        cursor = self.connection.execute(
            f"SELECT id, name FROM tags WHERE name IN ({placeholders})",
            normalized,
        )
        existing = {str(row["name"]): int(row["id"]) for row in cursor.fetchall()}
        missing = [name for name in normalized if name not in existing]
        if missing:
            with self.connection:
                for name in missing:
                    cursor = self.connection.execute(
                        "INSERT INTO tags (name) VALUES (?)",
                        (name,),
                    )
                    existing[name] = int(cursor.lastrowid)
        return existing

    def _set_host_tags(self, host_id: int, tags: list[str]) -> None:
        cleaned = [tag.strip() for tag in tags if tag.strip()]
        with self.connection:
            self.connection.execute("DELETE FROM host_tags WHERE host_id = ?", (host_id,))
            if not cleaned:
                return
            tag_ids = self._ensure_tags(cleaned)
            for name in cleaned:
                tag_id = tag_ids[name]
                self.connection.execute(
                    "INSERT OR IGNORE INTO host_tags (host_id, tag_id) VALUES (?, ?)",
                    (host_id, tag_id),
                )
