from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from pathlib import Path

from PySide6 import QtCore


SCHEMA_VERSION = 2


MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE IF NOT EXISTS groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE
    );

    CREATE TABLE IF NOT EXISTS hosts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        hostname TEXT NOT NULL,
        port INTEGER,
        user TEXT,
        identity_file TEXT,
        ssh_config_host_alias TEXT,
        notes TEXT,
        FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE
    );

    CREATE UNIQUE INDEX IF NOT EXISTS hosts_group_hostname_unique
        ON hosts(group_id, hostname);

    CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE
    );

    CREATE TABLE IF NOT EXISTS host_tags (
        host_id INTEGER NOT NULL,
        tag_id INTEGER NOT NULL,
        PRIMARY KEY (host_id, tag_id),
        FOREIGN KEY(host_id) REFERENCES hosts(id) ON DELETE CASCADE,
        FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
    );
    """,
    2: """
    ALTER TABLE hosts ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE hosts ADD COLUMN color TEXT;
    ALTER TABLE hosts ADD COLUMN tag TEXT;
    """,
}


def _get_app_data_dir() -> Path:
    location = QtCore.QStandardPaths.writableLocation(
        QtCore.QStandardPaths.StandardLocation.AppDataLocation
    )
    if not location:
        location = str(Path.home() / ".local" / "share" / "ShellDeck")
    path = Path(location)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_default_db_path() -> Path:
    return _get_app_data_dir() / "shelldeck.db"


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cursor.fetchone() is not None


def _get_schema_version(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "schema_meta"):
        conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_meta (version) VALUES (0)")
        conn.commit()
        return 0
    row = conn.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_meta (version) VALUES (0)")
        conn.commit()
        return 0
    return int(row[0])


def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute("UPDATE schema_meta SET version = ?", (version,))
    conn.commit()


def apply_migrations(conn: sqlite3.Connection) -> None:
    current = _get_schema_version(conn)
    for version in sorted(MIGRATIONS.keys()):
        if version <= current:
            continue
        conn.executescript(MIGRATIONS[version])
        _set_schema_version(conn, version)


@dataclass
class Database:
    connection: sqlite3.Connection

    @classmethod
    def open(cls, path: Path) -> "Database":
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        apply_migrations(connection)
        return cls(connection=connection)

    @classmethod
    def open_default(cls) -> "Database":
        return cls.open(get_default_db_path())

    def close(self) -> None:
        self.connection.close()
