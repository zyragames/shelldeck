#!/usr/bin/env python3

"""Flathub preflight + linter runner.

Typical usage:
  python3 tools/flathub_tester.py
  python3 tools/flathub_tester.py --strict --check-clean
  python3 tools/flathub_tester.py --build
  python3 tools/flathub_tester.py --export-submission /tmp/shelldeck-flathub-pr
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest
import xml.etree.ElementTree as ET


EXIT_OK = 0
EXIT_ERRORS = 2
EXIT_TOOLING = 3

KNOWN_APP_ID = "io.github.zyragames.shelldeck"
ALLOWED_FLATHUB_JSON_KEYS = {
    "only-arches",
    "skip-arches",
    "end-of-life",
    "end-of-life-rebase",
    "end-of-life-rebase-old-id",
}
ALLOWED_ARCHES = {"x86_64", "aarch64"}
LINTER_HINTS = {
    "finish-args-has-socket-ssh-auth": [
        "Remove `--socket=ssh-auth` from `finish-args`.",
        "Use Portals and app-private storage for key material.",
    ],
    "finish-args-ssh-filesystem-access": [
        "Remove `--filesystem=~/.ssh*` from `finish-args`.",
        "Use FileChooser Portal plus app-private storage.",
    ],
    "appid-url-not-reachable": [
        "Check App-ID and verification-domain alignment.",
        "For `io.github.*`, verify login-provider identity and URL ownership.",
        "Check homepage/bugtracker URLs for redirects or dead links.",
    ],
}


class Reporter:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self.counts = {"ERROR": 0, "WARN": 0, "OK": 0}

    def add(
        self,
        section: str,
        level: str,
        message: str,
        details: str = "",
        hints: list[str] | None = None,
    ) -> None:
        self.items.append(
            {
                "section": section,
                "level": level,
                "message": message,
                "details": details.strip(),
                "hints": hints or [],
            }
        )
        self.counts[level] += 1

    def ok(self, section: str, message: str, details: str = "") -> None:
        self.add(section, "OK", message, details)

    def warn(
        self, section: str, message: str, details: str = "", hints: list[str] | None = None
    ) -> None:
        self.add(section, "WARN", message, details, hints)

    def error(
        self, section: str, message: str, details: str = "", hints: list[str] | None = None
    ) -> None:
        self.add(section, "ERROR", message, details, hints)

    def print(self) -> None:
        by_section: dict[str, list[dict[str, Any]]] = {}
        for item in self.items:
            by_section.setdefault(item["section"], []).append(item)

        for section in by_section:
            print(f"\n== {section} ==")
            for item in by_section[section]:
                print(f"[{item['level']}] {item['message']}")
                if item["details"]:
                    for line in item["details"].splitlines():
                        print(f"  {line}")
                if item["hints"]:
                    print("  Fix hints:")
                    for hint in item["hints"]:
                        print(f"   - {hint}")


def run_cmd(args: list[str], check: bool = False, cwd: Path | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(args)}\n{proc.stderr}")
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def detect_tooling() -> dict[str, Any]:
    flatpak = shutil.which("flatpak")
    host_builder = shutil.which("flatpak-builder")
    host_lint = shutil.which("flatpak-builder-lint")
    host_flathub_build = shutil.which("flathub-build")
    runtime_builder = False
    if flatpak:
        rc, _, _ = run_cmd(["flatpak", "info", "org.flatpak.Builder"])
        runtime_builder = rc == 0

    return {
        "flatpak": bool(flatpak),
        "runtime_builder": runtime_builder,
        "host_builder": bool(host_builder),
        "host_lint": bool(host_lint),
        "host_flathub_build": bool(host_flathub_build),
    }


def builder_show_manifest_cmd(tooling: dict[str, Any]) -> list[str] | None:
    if tooling["flatpak"] and tooling["runtime_builder"]:
        return [
            "flatpak",
            "run",
            "--command=flatpak-builder",
            "org.flatpak.Builder",
            "--show-manifest",
        ]
    if tooling["host_builder"]:
        return ["flatpak-builder", "--show-manifest"]
    return None


def lint_cmd(tooling: dict[str, Any], kind: str, target: Path) -> list[str] | None:
    if tooling["flatpak"] and tooling["runtime_builder"]:
        return [
            "flatpak",
            "run",
            "--command=flatpak-builder-lint",
            "org.flatpak.Builder",
            kind,
            str(target),
        ]
    if tooling["host_lint"]:
        return ["flatpak-builder-lint", kind, str(target)]
    return None


def flathub_build_cmd(
    tooling: dict[str, Any], repo_path: Path, manifest_path: Path
) -> list[str] | None:
    if tooling["flatpak"] and tooling["runtime_builder"]:
        return [
            "flatpak",
            "run",
            "--command=flathub-build",
            "org.flatpak.Builder",
            f"--repo={repo_path}",
            str(manifest_path),
        ]
    if tooling["host_flathub_build"]:
        return ["flathub-build", f"--repo={repo_path}", str(manifest_path)]
    return None


def resolve_manifest_to_json(manifest_path: Path, tooling: dict[str, Any]) -> dict[str, Any]:
    base_cmd = builder_show_manifest_cmd(tooling)
    if not base_cmd:
        raise RuntimeError(
            "Neither org.flatpak.Builder nor host flatpak-builder available for --show-manifest"
        )
    rc, out, err = run_cmd(base_cmd + [str(manifest_path)])
    if rc != 0:
        raise RuntimeError(f"show-manifest failed for {manifest_path}\n{err.strip()}")
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"show-manifest output is not valid JSON: {exc}") from exc


def extract_linter_ids(text: str) -> list[str]:
    ids = sorted(set(re.findall(r"\b([a-z0-9]+(?:-[a-z0-9]+)+)\b", text)))
    return [item for item in ids if item.count("-") >= 2]


def compact_output(stdout: str, stderr: str, max_lines: int = 12) -> str:
    lines = []
    for part in (stdout.strip(), stderr.strip()):
        if part:
            lines.extend(part.splitlines())
    if not lines:
        return ""
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[:max_lines] + [f"... ({len(lines) - max_lines} more lines)"])


def detect_manifest(
    repo_root: Path, tooling: dict[str, Any], preferred_appid: str | None
) -> tuple[Path | None, str | None]:
    root_candidates = sorted(
        [p for ext in ("*.yml", "*.yaml", "*.json") for p in repo_root.glob(ext) if p.is_file()]
    )
    if preferred_appid:
        for suffix in (".yml", ".yaml", ".json"):
            preferred = repo_root / f"{preferred_appid}{suffix}"
            if preferred.exists():
                return preferred.resolve(), None

    valid: list[Path] = []
    problems: list[str] = []
    for candidate in root_candidates:
        try:
            resolved = resolve_manifest_to_json(candidate, tooling)
            if isinstance(resolved, dict) and resolved.get("app-id"):
                valid.append(candidate.resolve())
        except RuntimeError as exc:
            problems.append(f"{candidate.name}: {exc}")

    if len(valid) == 1:
        return valid[0], None
    if len(valid) == 0:
        if not root_candidates:
            return None, "No manifest found in repo root (*.yml/*.yaml/*.json)."
        if problems:
            return None, "No root manifest could be resolved via --show-manifest."
        return None, "No root manifest with `app-id` found."
    listed = "\n".join(f"- {p}" for p in valid)
    return None, f"Multiple valid root manifests found; pass --manifest.\n{listed}"


def find_metainfo(repo_root: Path, app_id: str | None) -> Path | None:
    if app_id:
        patterns = [
            f"data/**/{app_id}.metainfo.xml",
            f"**/share/metainfo/{app_id}.metainfo.xml",
            f"**/{app_id}.metainfo.xml",
        ]
        for pattern in patterns:
            found = sorted(repo_root.glob(pattern))
            if found:
                return found[0].resolve()
    fallback = sorted(repo_root.glob("**/*.metainfo.xml"))
    if fallback:
        return fallback[0].resolve()
    return None


def find_desktop_and_icon(repo_root: Path, app_id: str | None) -> tuple[Path | None, Path | None]:
    desktops = sorted(repo_root.glob("**/*.desktop"))
    icon_candidates = sorted(repo_root.glob("**/*.svg")) + sorted(repo_root.glob("**/*.png"))

    desktop = None
    if app_id:
        preferred = [p for p in desktops if p.name == f"{app_id}.desktop"]
        if preferred:
            desktop = preferred[0].resolve()
    if not desktop and desktops:
        desktop = desktops[0].resolve()

    icon = None
    if app_id:
        preferred_icon = [
            p for p in icon_candidates if p.stem == app_id or p.name.startswith(app_id + ".")
        ]
        if preferred_icon:
            icon = preferred_icon[0].resolve()
    if not icon and icon_candidates:
        icon = icon_candidates[0].resolve()
    return desktop, icon


def ensure_line_in_file(file_path: Path, line: str) -> bool:
    existing = ""
    if file_path.exists():
        existing = file_path.read_text(encoding="utf-8", errors="ignore")
    lines = [item.strip() for item in existing.splitlines()]
    if line.strip() in lines:
        return False
    if existing and not existing.endswith("\n"):
        existing += "\n"
    file_path.write_text(existing + f"{line}\n", encoding="utf-8")
    return True


def relative_posix(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def lint_with_builder(
    kind: str, target: Path, tooling: dict[str, Any], reporter: Reporter, section: str
) -> bool:
    cmd = lint_cmd(tooling, kind, target)
    if not cmd:
        reporter.error(
            section,
            f"`flatpak-builder-lint {kind}` unavailable",
            "Missing org.flatpak.Builder or host flatpak-builder-lint.",
        )
        return False

    rc, out, err = run_cmd(cmd)
    if rc == 0:
        reporter.ok(section, f"`flatpak-builder-lint {kind}` passed", str(target))
        return True

    merged = "\n".join([out, err]).strip()
    lint_ids = extract_linter_ids(merged)
    hints: list[str] = []
    for lint_id in lint_ids:
        hints.extend(LINTER_HINTS.get(lint_id, []))

    detail = compact_output(out, err)
    if lint_ids:
        detail = (
            f"IDs: {', '.join(lint_ids)}\n{detail}" if detail else f"IDs: {', '.join(lint_ids)}"
        )
    reporter.error(section, f"`flatpak-builder-lint {kind}` failed", detail, hints)
    return False


def flatten_modules(modules: list[Any]) -> list[dict[str, Any]]:
    flat: list[dict[str, Any]] = []
    for module in modules or []:
        if isinstance(module, dict):
            flat.append(module)
            nested = module.get("modules")
            if isinstance(nested, list):
                flat.extend(flatten_modules(nested))
    return flat


def check_manifest_location_and_naming(
    reporter: Reporter,
    repo_root: Path,
    manifest_path: Path,
    app_id: str,
    manifest_json: dict[str, Any],
) -> None:
    section = "Preflight: Manifest"
    if manifest_path.parent.resolve() != repo_root.resolve():
        reporter.error(
            section,
            "Manifest is not in repo root",
            f"Found: {manifest_path}",
            ["Move manifest to repository root."],
        )
    else:
        reporter.ok(section, "Manifest is in repo root", str(manifest_path))

    expected_names = {f"{app_id}.yml", f"{app_id}.yaml", f"{app_id}.json"}
    if manifest_path.name not in expected_names:
        reporter.error(
            section,
            "Manifest filename does not match app-id",
            f"Expected one of: {', '.join(sorted(expected_names))}\nFound: {manifest_path.name}",
            ["Rename manifest to `<app-id>.yml` and keep it at repo root."],
        )
    else:
        reporter.ok(section, "Manifest filename matches app-id", manifest_path.name)

    components = [item for item in app_id.split(".") if item]
    if len(app_id) > 255:
        reporter.error(section, "App-ID exceeds 255 chars", app_id)
    elif not (3 <= len(components) <= 5):
        reporter.error(section, "App-ID should have 3..5 components", app_id)
    else:
        reporter.ok(section, "App-ID shape looks valid", app_id)

    runtime = manifest_json.get("runtime")
    sdk = manifest_json.get("sdk")
    if runtime:
        reporter.ok(section, "Runtime set", str(runtime))
    else:
        reporter.warn(section, "Runtime missing", "Add `runtime` to manifest root.")
    if sdk:
        reporter.ok(section, "SDK set", str(sdk))
    else:
        reporter.warn(section, "SDK missing", "Add `sdk` to manifest root.")


def check_permissions_and_offline_build(reporter: Reporter, manifest_json: dict[str, Any]) -> None:
    section = "Preflight: Permissions"
    finish_args = manifest_json.get("finish-args") or []
    finish_args = [str(item) for item in finish_args if isinstance(item, str)]

    hard_patterns = [
        "--socket=ssh-auth",
        "--socket=ssh-agent",
        "--filesystem=~/.ssh",
        "--filesystem=home",
        "--filesystem=~",
        "--filesystem=/home",
    ]
    warn_patterns = [
        "--filesystem=host",
        "--device=all",
        "--talk-name=*",
        "--system-bus",
        "--filesystem=xdg-run/",
    ]

    for arg in finish_args:
        if any(arg == pat or arg.startswith(pat) for pat in hard_patterns):
            reporter.error(section, f"Disallowed static permission: {arg}")
        elif any(arg == pat or arg.startswith(pat) for pat in warn_patterns):
            reporter.warn(
                section,
                f"Broad static permission: {arg}",
                "Minimize static permissions where possible.",
            )

    if not finish_args:
        reporter.warn(
            section, "No finish-args found", "Ensure sandbox permissions are explicitly reviewed."
        )
    else:
        reporter.ok(section, "finish-args parsed", f"Count: {len(finish_args)}")

    network_hits: list[str] = []

    def probe_build_args(obj: dict[str, Any], label: str) -> None:
        build_opts = obj.get("build-options") if isinstance(obj, dict) else None
        if not isinstance(build_opts, dict):
            return
        build_args = build_opts.get("build-args")
        if not isinstance(build_args, list):
            return
        for entry in build_args:
            if isinstance(entry, str) and "--share=network" in entry:
                network_hits.append(f"{label}: {entry}")

    probe_build_args(manifest_json, "manifest")
    for idx, module in enumerate(flatten_modules(manifest_json.get("modules") or [])):
        mod_name = module.get("name") or f"module[{idx}]"
        probe_build_args(module, str(mod_name))

    if network_hits:
        reporter.error(
            section,
            "Build args include `--share=network`",
            "\n".join(network_hits),
            ["Remove network sharing from build args; Flathub builds run offline."],
        )
    else:
        reporter.ok(section, "No offline-build violations found")


def source_url_private(url_value: str) -> bool:
    parsed = urlparse.urlparse(url_value)
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    if host.endswith(".local") or host.endswith(".internal"):
        return True
    return False


def check_sources(reporter: Reporter, manifest_json: dict[str, Any]) -> None:
    section = "Preflight: Sources"
    modules = flatten_modules(manifest_json.get("modules") or [])
    if not modules:
        reporter.warn(section, "No modules found in resolved manifest")
        return

    checks = 0
    for idx, module in enumerate(modules):
        mod_name = module.get("name") or f"module[{idx}]"
        sources = module.get("sources") or []
        if not isinstance(sources, list):
            continue
        for source in sources:
            if not isinstance(source, dict):
                continue
            checks += 1
            source_type = source.get("type")
            url = source.get("url")
            sha = source.get("sha256")

            if source_type in {"archive", "file", "extra-data"} and url and not sha:
                reporter.error(
                    section, f"Missing sha256 for {source_type} source in {mod_name}", str(url)
                )

            if source_type == "git":
                has_branch = bool(source.get("branch"))
                has_commit_or_tag = bool(source.get("commit") or source.get("tag"))
                if has_branch and not has_commit_or_tag:
                    reporter.warn(
                        section,
                        f"Git source uses branch without commit/tag in {mod_name}",
                        str(source.get("branch")),
                    )

            if isinstance(url, str) and source_url_private(url):
                reporter.warn(section, f"Source URL looks private/local in {mod_name}", url)

    reporter.ok(section, "Source scan complete", f"Checked {checks} source entries")


def check_license_install_heuristic(reporter: Reporter, manifest_json: dict[str, Any]) -> None:
    section = "Preflight: License install"
    modules = flatten_modules(manifest_json.get("modules") or [])
    interesting = [m for m in modules if isinstance(m.get("buildsystem"), str)]
    if not interesting:
        reporter.warn(section, "No buildsystem modules found for license heuristic")
        return

    hit = False
    patterns = (
        "/share/licenses/$FLATPAK_ID",
        "${FLATPAK_DEST}/share/licenses/$FLATPAK_ID",
    )
    for module in interesting:
        for key in ("install-commands", "build-commands"):
            commands = module.get(key)
            if not isinstance(commands, list):
                continue
            for cmd in commands:
                if isinstance(cmd, str) and any(token in cmd for token in patterns):
                    hit = True
                    break
            if hit:
                break
        if hit:
            break

    if hit:
        reporter.ok(section, "License install command pattern detected")
    else:
        reporter.warn(
            section,
            "No obvious license install command detected",
            "Heuristic only; install LICENSE/COPYING under `${FLATPAK_DEST}/share/licenses/$FLATPAK_ID/`.",
        )


def check_repo_hygiene(reporter: Reporter, repo_root: Path) -> None:
    section = "Preflight: Repo hygiene"
    blocked = [repo_root / ".flatpak-builder", repo_root / "build", repo_root / "repo"]
    found_blocked = [str(path) for path in blocked if path.exists()]
    if found_blocked:
        reporter.error(section, "Build artifacts found in repo", "\n".join(found_blocked))
    else:
        reporter.ok(section, "No top-level build artifacts found")

    pycache_hits = [
        str(p) for p in repo_root.glob("**/__pycache__") if p.is_dir() and ".git" not in p.parts
    ]
    pyc_hits = [str(p) for p in repo_root.glob("**/*.pyc") if p.is_file() and ".git" not in p.parts]
    flatpak_hits = [
        str(p) for p in repo_root.glob("**/*.flatpak") if p.is_file() and ".git" not in p.parts
    ]

    if pycache_hits or pyc_hits or flatpak_hits:
        lines = []
        lines.extend(pycache_hits[:20])
        lines.extend(pyc_hits[:20])
        lines.extend(flatpak_hits[:20])
        reporter.warn(section, "Generated files present", "\n".join(lines))
    else:
        reporter.ok(section, "No obvious generated files detected")


def check_git_clean(reporter: Reporter, repo_root: Path, workdir: Path) -> None:
    section = "Preflight: Git clean"
    rc, out, err = run_cmd(["git", "status", "--porcelain"], cwd=repo_root)
    if rc != 0:
        reporter.warn(section, "`git status --porcelain` failed", err.strip() or out.strip())
        return

    rel_workdir = relative_posix(workdir, repo_root).rstrip("/") + "/"
    dirty: list[str] = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        path_part = line[3:]
        if " -> " in path_part:
            path_part = path_part.split(" -> ", 1)[1]
        path_part = path_part.strip()
        if path_part.startswith(rel_workdir):
            continue
        dirty.append(line)

    if dirty:
        reporter.warn(section, "Working tree is not clean", "\n".join(dirty[:30]))
    else:
        reporter.ok(section, "Working tree clean (excluding tester workdir)")


def check_metainfo(
    reporter: Reporter, metainfo_path: Path | None, app_id: str, no_net: bool
) -> None:
    section = "Preflight: Metainfo"
    if not metainfo_path:
        reporter.error(section, "Metainfo file not found")
        return

    reporter.ok(section, "Metainfo detected", str(metainfo_path))
    try:
        tree = ET.parse(metainfo_path)
        root = tree.getroot()
    except ET.ParseError as exc:
        reporter.error(section, "Metainfo XML parse failed", str(exc))
        return

    def text_of(path: str) -> str:
        node = root.find(path)
        if node is None or node.text is None:
            return ""
        return node.text.strip()

    component_id = text_of("id")
    if component_id != app_id:
        reporter.error(
            section,
            "`<id>` does not match app-id",
            f"metainfo: {component_id or '<missing>'}\nmanifest: {app_id}",
        )
    else:
        reporter.ok(section, "`<id>` matches app-id")

    required_simple = ["metadata_license", "project_license"]
    for tag in required_simple:
        value = text_of(tag)
        if value:
            reporter.ok(section, f"`<{tag}>` present", value)
        else:
            reporter.error(section, f"`<{tag}>` missing")

    dev = root.find("developer")
    dev_name = root.find("developer/name")
    if (
        dev is not None
        and dev.attrib.get("id")
        and dev_name is not None
        and (dev_name.text or "").strip()
    ):
        reporter.ok(section, "`<developer id><name>` present")
    else:
        reporter.error(
            section,
            "Developer metadata missing",
            'Need `<developer id="..."><name>...</name></developer>`',
        )

    launchable = None
    for node in root.findall("launchable"):
        if node.attrib.get("type") == "desktop-id":
            launchable = (node.text or "").strip()
            break
    if launchable:
        reporter.ok(section, "Desktop launchable present", launchable)
    else:
        reporter.error(section, 'Missing `<launchable type="desktop-id">`')

    if no_net:
        reporter.ok(section, "URL reachability checks skipped", "--no-net enabled")
        return

    for url_type in ("homepage", "bugtracker"):
        node = root.find(f"url[@type='{url_type}']")
        if node is None or not (node.text or "").strip():
            reporter.warn(section, f'`<url type="{url_type}">` missing')
            continue
        url_value = (node.text or "").strip()
        try:
            req = urlrequest.Request(url_value, method="HEAD")
            with urlrequest.urlopen(req, timeout=12) as response:
                code = int(getattr(response, "status", 200))
            if code >= 400:
                reporter.error(
                    section, f"{url_type} URL not reachable", f"{url_value} -> HTTP {code}"
                )
            else:
                reporter.ok(section, f"{url_type} URL reachable", f"{url_value} -> HTTP {code}")
        except Exception:
            try:
                with urlrequest.urlopen(url_value, timeout=12) as response:
                    code = int(getattr(response, "status", 200))
                if code >= 400:
                    reporter.error(
                        section, f"{url_type} URL not reachable", f"{url_value} -> HTTP {code}"
                    )
                else:
                    reporter.ok(section, f"{url_type} URL reachable", f"{url_value} -> HTTP {code}")
            except (urlerror.URLError, urlerror.HTTPError, TimeoutError) as exc:
                reporter.error(section, f"{url_type} URL not reachable", f"{url_value}\n{exc}")


def check_flathub_json(reporter: Reporter, repo_root: Path) -> None:
    section = "Preflight: flathub.json"
    path = repo_root / "flathub.json"
    if not path.exists():
        reporter.warn(
            section, "No flathub.json", "Optional; useful if only some arches are supported."
        )
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        reporter.error(section, "Invalid flathub.json", str(exc))
        return

    if not isinstance(data, dict):
        reporter.error(section, "flathub.json must be an object")
        return

    unknown = sorted(set(data.keys()) - ALLOWED_FLATHUB_JSON_KEYS)
    if unknown:
        reporter.warn(section, "Unknown flathub.json keys", ", ".join(unknown))
    else:
        reporter.ok(section, "flathub.json keys recognized")

    if "only-arches" in data and "skip-arches" in data:
        reporter.error(section, "`only-arches` and `skip-arches` cannot both be set")

    for key in ("only-arches", "skip-arches"):
        if key not in data:
            continue
        value = data[key]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            reporter.error(section, f"`{key}` must be list[str]")
            continue
        invalid = [item for item in value if item not in ALLOWED_ARCHES]
        if invalid:
            reporter.error(section, f"`{key}` contains unsupported arches", ", ".join(invalid))
        else:
            reporter.ok(section, f"`{key}` arches look valid", ", ".join(value))


def extract_dependency_manifest_refs(manifest_path: Path, repo_root: Path) -> list[Path]:
    refs: list[Path] = []
    suffix = manifest_path.suffix.lower()
    text = manifest_path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".json":
        try:
            data = json.loads(text)
            modules = data.get("modules") if isinstance(data, dict) else None
            if isinstance(modules, list):
                for item in modules:
                    if isinstance(item, str) and item.endswith((".json", ".yml", ".yaml")):
                        refs.append((manifest_path.parent / item).resolve())
            return refs
        except Exception:
            pass

    for match in re.finditer(r"^\s*-\s*([\w./-]+\.(?:json|ya?ml))\s*$", text, flags=re.MULTILINE):
        candidate = (manifest_path.parent / match.group(1)).resolve()
        if candidate.exists() and candidate.is_file():
            refs.append(candidate)
    unique = []
    seen: set[Path] = set()
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            unique.append(ref)
    return unique


def collect_local_patch_files(
    manifest_json: dict[str, Any], repo_root: Path
) -> tuple[list[Path], list[str]]:
    patches: list[Path] = []
    warnings: list[str] = []
    modules = flatten_modules(manifest_json.get("modules") or [])
    for module in modules:
        sources = module.get("sources")
        if not isinstance(sources, list):
            continue
        for source in sources:
            if not isinstance(source, dict):
                continue
            if source.get("type") != "file":
                continue
            path_value = source.get("path")
            if not isinstance(path_value, str):
                continue
            candidate = (repo_root / path_value).resolve()
            if not candidate.exists() or not candidate.is_file():
                continue
            lower = candidate.name.lower()
            if lower.endswith((".patch", ".diff")):
                patches.append(candidate)
            else:
                warnings.append(f"Skipped non-patch file source: {candidate}")
    unique = []
    seen: set[Path] = set()
    for item in patches:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique, warnings


def copy_relative(src: Path, repo_root: Path, dst_root: Path) -> bool:
    try:
        rel = src.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return False
    dst = (dst_root / rel).resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def export_submission_bundle(
    reporter: Reporter,
    repo_root: Path,
    manifest_path: Path,
    manifest_json: dict[str, Any],
    export_dir: Path,
) -> None:
    section = "Submission export"
    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    copied: list[Path] = []
    copy_relative(manifest_path, repo_root, export_dir)
    copied.append(manifest_path)

    flathub_json = repo_root / "flathub.json"
    if flathub_json.exists():
        if copy_relative(flathub_json, repo_root, export_dir):
            copied.append(flathub_json)

    visited: set[Path] = set()
    queue: list[Path] = [manifest_path]
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        for dep in extract_dependency_manifest_refs(current, repo_root):
            if not dep.exists() or not dep.is_file():
                continue
            if copy_relative(dep, repo_root, export_dir):
                copied.append(dep)
            queue.append(dep)

    patch_files, patch_warnings = collect_local_patch_files(manifest_json, repo_root)
    for patch in patch_files:
        if copy_relative(patch, repo_root, export_dir):
            copied.append(patch)
    for warning in patch_warnings:
        reporter.warn(section, warning)

    reporter.ok(section, "Submission files exported", f"{len(copied)} files -> {export_dir}")
    reporter.ok(
        section,
        "Ready for flathub/flathub new-pr",
        "Commit exported directory contents to your new-pr branch.",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Flathub submission preflight + lints")
    parser.add_argument("--manifest", help="Path to Flatpak manifest")
    parser.add_argument("--metainfo", help="Path to metainfo XML")
    parser.add_argument(
        "--workdir",
        default=".flathub-test",
        help="Workspace for build/repo artifacts (default: ./.flathub-test)",
    )
    parser.add_argument("--no-net", action="store_true", help="Skip URL reachability checks")
    parser.add_argument("--strict", action="store_true", help="Treat WARN as ERROR for exit code")
    parser.add_argument(
        "--build",
        action="store_true",
        help="Run flathub-build into workdir and lint generated repo",
    )
    parser.add_argument("--repo", help="Existing repo path to lint (default: <workdir>/repo)")
    parser.add_argument("--export-submission", help="Export required submission files to directory")
    parser.add_argument(
        "--check-clean", action="store_true", help="Check git working tree cleanliness"
    )
    parser.add_argument(
        "--fix-gitignore",
        action="store_true",
        help="Append common artifact patterns to .gitignore when missing",
    )
    args = parser.parse_args()

    repo_root = Path.cwd().resolve()
    reporter = Reporter()

    tooling = detect_tooling()
    section = "Tooling"
    if tooling["flatpak"]:
        reporter.ok(section, "`flatpak` found")
    else:
        reporter.warn(
            section, "`flatpak` not found", "Will fall back to host binaries where possible."
        )
    if tooling["runtime_builder"]:
        reporter.ok(section, "`org.flatpak.Builder` runtime available")
    else:
        reporter.warn(section, "`org.flatpak.Builder` runtime unavailable")
    if not (tooling["runtime_builder"] or tooling["host_builder"]):
        reporter.error(
            section,
            "No manifest resolver available",
            "Install org.flatpak.Builder or host `flatpak-builder`.",
        )
    if not (tooling["runtime_builder"] or tooling["host_lint"]):
        reporter.error(
            section,
            "No linter available",
            "Install org.flatpak.Builder or host `flatpak-builder-lint`.",
        )

    workdir = Path(args.workdir)
    if not workdir.is_absolute():
        workdir = (repo_root / workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    workdir_line = relative_posix(workdir, repo_root).rstrip("/") + "/"
    gitignore_path = repo_root / ".gitignore"
    changed = ensure_line_in_file(gitignore_path, workdir_line)
    if changed:
        reporter.ok("Workspace", "Added workdir to .gitignore", workdir_line)
    else:
        reporter.ok("Workspace", "Workdir already ignored", workdir_line)

    if args.fix_gitignore:
        for pattern in [
            ".flatpak-builder/",
            "build/",
            "repo/",
            "__pycache__/",
            "*.pyc",
            "*.flatpak",
        ]:
            ensure_line_in_file(gitignore_path, pattern)
        reporter.ok("Workspace", "Applied --fix-gitignore patterns")

    manifest_path: Path | None
    if args.manifest:
        manifest_path = Path(args.manifest)
        if not manifest_path.is_absolute():
            manifest_path = (repo_root / manifest_path).resolve()
        if not manifest_path.exists():
            reporter.error("Discovery", "Manifest path does not exist", str(manifest_path))
            manifest_path = None
    else:
        manifest_path, issue = detect_manifest(repo_root, tooling, KNOWN_APP_ID)
        if manifest_path:
            reporter.ok("Discovery", "Manifest autodetected", str(manifest_path))
        else:
            reporter.error("Discovery", "Manifest autodetection failed", issue or "Unknown error")

    if not manifest_path:
        reporter.print()
        print("\nSummary")
        print(f"- ERROR: {reporter.counts['ERROR']}")
        print(f"- WARN: {reporter.counts['WARN']}")
        print(f"- OK: {reporter.counts['OK']}")
        return EXIT_ERRORS

    app_id = ""
    manifest_json: dict[str, Any] = {}
    try:
        manifest_json = resolve_manifest_to_json(manifest_path, tooling)
        app_id = str(manifest_json.get("app-id") or manifest_json.get("id") or "")
        if app_id:
            reporter.ok("Discovery", "Resolved app-id from manifest", app_id)
        else:
            reporter.error("Discovery", "Resolved manifest missing app-id")
    except RuntimeError as exc:
        reporter.error("Discovery", "Unable to resolve manifest via --show-manifest", str(exc))

    metainfo_path: Path | None = None
    if args.metainfo:
        metainfo_path = Path(args.metainfo)
        if not metainfo_path.is_absolute():
            metainfo_path = (repo_root / metainfo_path).resolve()
        if not metainfo_path.exists():
            reporter.error("Discovery", "Metainfo path does not exist", str(metainfo_path))
            metainfo_path = None
    elif app_id:
        metainfo_path = find_metainfo(repo_root, app_id)

    desktop_path, icon_path = find_desktop_and_icon(repo_root, app_id or None)
    if desktop_path:
        reporter.ok("Discovery", "Desktop file detected", str(desktop_path))
    else:
        reporter.warn("Discovery", "No desktop file detected")
    if icon_path:
        icon_note = str(icon_path)
        if icon_path.suffix.lower() == ".png":
            icon_note += " (PNG: verify >=256x256)"
        reporter.ok("Discovery", "Icon candidate detected", icon_note)
    else:
        reporter.warn("Discovery", "No icon candidate detected")

    if app_id:
        check_manifest_location_and_naming(
            reporter, repo_root, manifest_path, app_id, manifest_json
        )
        check_permissions_and_offline_build(reporter, manifest_json)
        check_sources(reporter, manifest_json)
        check_license_install_heuristic(reporter, manifest_json)
        check_metainfo(reporter, metainfo_path, app_id, args.no_net)
    check_flathub_json(reporter, repo_root)
    check_repo_hygiene(reporter, repo_root)

    if args.check_clean:
        check_git_clean(reporter, repo_root, workdir)

    lint_ok = True
    lint_ok = lint_with_builder("manifest", manifest_path, tooling, reporter, "Linter") and lint_ok
    if metainfo_path:
        lint_ok = (
            lint_with_builder("appstream", metainfo_path, tooling, reporter, "Linter") and lint_ok
        )
    else:
        reporter.error("Linter", "Cannot run appstream lint", "Metainfo file not found.")
        lint_ok = False

    repo_to_lint = Path(args.repo).resolve() if args.repo else (workdir / "repo").resolve()
    if args.build:
        build_cmd = flathub_build_cmd(tooling, repo_to_lint, manifest_path)
        if not build_cmd:
            reporter.error(
                "Build",
                "flathub-build unavailable",
                "Need org.flatpak.Builder or host flathub-build",
            )
        else:
            repo_to_lint.parent.mkdir(parents=True, exist_ok=True)
            rc, out, err = run_cmd(build_cmd, cwd=workdir)
            if rc != 0:
                reporter.error("Build", "flathub-build failed", compact_output(out, err))
            else:
                reporter.ok("Build", "flathub-build completed", str(repo_to_lint))

    if repo_to_lint.exists():
        lint_with_builder("repo", repo_to_lint, tooling, reporter, "Linter")
    elif args.repo or args.build:
        reporter.error("Linter", "Repo path for lint does not exist", str(repo_to_lint))
    else:
        reporter.warn(
            "Linter", "Repo lint skipped", f"No repo at {repo_to_lint}. Use --build or --repo."
        )

    if args.export_submission:
        export_dir = Path(args.export_submission)
        if not export_dir.is_absolute():
            export_dir = (repo_root / export_dir).resolve()
        export_submission_bundle(reporter, repo_root, manifest_path, manifest_json, export_dir)

    reporter.print()
    print("\nSummary")
    print(f"- ERROR: {reporter.counts['ERROR']}")
    print(f"- WARN: {reporter.counts['WARN']}")
    print(f"- OK: {reporter.counts['OK']}")

    tooling_errors = any(
        item["level"] == "ERROR" and item["section"] == "Tooling" for item in reporter.items
    )
    errors = reporter.counts["ERROR"]
    warns = reporter.counts["WARN"]
    if tooling_errors:
        print(f"- Exit code: {EXIT_TOOLING}")
        return EXIT_TOOLING
    if errors > 0 or (args.strict and warns > 0):
        print(f"- Exit code: {EXIT_ERRORS}")
        return EXIT_ERRORS
    print(f"- Exit code: {EXIT_OK}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
