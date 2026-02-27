from __future__ import annotations

import json
from pathlib import Path
import tempfile

from .data import Repository, export_json, import_json
from .data.models import Host


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "shelldeck.db"
        repo = Repository.open(db_path)
        group = repo.create_group("Test")
        host = Host(
            id=0,
            group_id=group.id,
            name="web-01",
            hostname="10.0.0.10",
            port=22,
            user="ubuntu",
            identity_file=None,
            ssh_config_host_alias=None,
            notes="demo",
            tags=["prod", "web"],
            favorite=False,
            color=None,
            tag=None,
        )
        repo.create_host(host)

        export_path = Path(tmpdir) / "export.json"
        export_json(repo, export_path, settings={"theme": {"mode": "dark"}})
        payload = json.loads(export_path.read_text(encoding="utf-8"))
        assert payload["hosts"], "Expected hosts in export"

        repo2 = Repository.open(Path(tmpdir) / "import.db")
        result = import_json(repo2, export_path)
        assert result.hosts_inserted == 1
        assert result.groups_added == 1
        repo.close()
        repo2.close()


if __name__ == "__main__":
    main()
