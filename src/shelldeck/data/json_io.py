from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path

from .models import Host
from .repository import Repository


@dataclass(frozen=True)
class ImportResult:
    groups_added: int
    hosts_inserted: int
    hosts_updated: int


def export_json(repository: Repository, path: str | Path, settings: dict | None = None) -> None:
    groups = repository.list_groups()
    data = {
        "schema_version": 2,
        "exported_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "groups": [{"name": group.name} for group in groups],
        "hosts": [],
        "tags": [],
    }
    if settings:
        data["settings"] = settings

    tags_set: set[str] = set()
    for group in groups:
        for host in repository.list_hosts_for_group(group.id):
            tags_set.update(host.tags)
            data["hosts"].append(
                {
                    "name": host.name,
                    "group": group.name,
                    "hostname": host.hostname,
                    "port": host.port,
                    "user": host.user,
                    "identity_file": host.identity_file,
                    "ssh_config_host_alias": host.ssh_config_host_alias,
                    "notes": host.notes,
                    "tags": host.tags,
                    "favorite": host.favorite,
                    "color": host.color,
                    "tag": host.tag,
                }
            )

    data["tags"] = sorted(tags_set)

    output_path = Path(path)
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def import_json(repository: Repository, path: str | Path) -> ImportResult:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    groups_added = 0
    hosts_inserted = 0
    hosts_updated = 0

    groups_by_name: dict[str, int] = {group.name: group.id for group in repository.list_groups()}
    for group_payload in data.get("groups", []):
        name = str(group_payload.get("name", "")).strip()
        if not name or name in groups_by_name:
            continue
        group = repository.create_group(name)
        groups_by_name[group.name] = group.id
        groups_added += 1

    for host_payload in data.get("hosts", []):
        group_name = str(host_payload.get("group", "")).strip() or "Imported"
        group_id = groups_by_name.get(group_name)
        if group_id is None:
            group = repository.create_group(group_name)
            groups_by_name[group.name] = group.id
            group_id = group.id
            groups_added += 1

        name = str(host_payload.get("name", "")).strip() or "Unnamed"
        hostname = str(host_payload.get("hostname", "")).strip()
        user = host_payload.get("user")
        port = host_payload.get("port")
        identity_file = host_payload.get("identity_file")
        ssh_config_host_alias = host_payload.get("ssh_config_host_alias")
        notes = host_payload.get("notes")
        tags = [str(tag) for tag in host_payload.get("tags", []) if str(tag).strip()]
        favorite = bool(host_payload.get("favorite", False))
        color = host_payload.get("color")
        tag = host_payload.get("tag")

        existing = repository.find_host_for_merge(group_id, hostname or None, name or None)
        if existing:
            updated = Host(
                id=existing.id,
                group_id=group_id,
                name=name,
                hostname=hostname or existing.hostname,
                port=int(port) if port is not None else existing.port,
                user=str(user) if user is not None else existing.user,
                identity_file=(
                    str(identity_file) if identity_file is not None else existing.identity_file
                ),
                ssh_config_host_alias=(
                    str(ssh_config_host_alias)
                    if ssh_config_host_alias is not None
                    else existing.ssh_config_host_alias
                ),
                notes=str(notes) if notes is not None else existing.notes,
                tags=tags or existing.tags,
                favorite=favorite if "favorite" in host_payload else existing.favorite,
                color=str(color) if color is not None else existing.color,
                tag=str(tag) if tag is not None else existing.tag,
            )
            repository.update_host(updated)
            hosts_updated += 1
        else:
            created = Host(
                id=0,
                group_id=group_id,
                name=name,
                hostname=hostname or name,
                port=int(port) if port is not None else None,
                user=str(user) if user is not None else None,
                identity_file=str(identity_file) if identity_file is not None else None,
                ssh_config_host_alias=str(ssh_config_host_alias)
                if ssh_config_host_alias is not None
                else None,
                notes=str(notes) if notes is not None else None,
                tags=tags,
                favorite=favorite,
                color=str(color) if color is not None else None,
                tag=str(tag) if tag is not None else None,
            )
            repository.create_host(created)
            hosts_inserted += 1

    return ImportResult(
        groups_added=groups_added,
        hosts_inserted=hosts_inserted,
        hosts_updated=hosts_updated,
    )
