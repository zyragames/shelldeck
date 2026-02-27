#!/usr/bin/env python3

import argparse
from dataclasses import dataclass, asdict
from pathlib import Path
import subprocess
import tempfile
import shutil
import json
import re
import sys
import os


EXIT_OK = 0
EXIT_HARD_FAIL = 1
EXIT_MISSING_BINARY = 2
EXIT_BROKEN_ENV = 3
EXIT_BUNDLE_IMPORT_FAIL = 4

WALK_SKIP_DIRS = {
    ".git",
    ".venv",
    ".flatpak-builder",
    "build",
    "builddir",
    "build-dir",
    "dist",
    "repo",
}


@dataclass
class CheckResult:
    name: str
    status: str
    hard: bool = False
    soft: bool = False
    warning: bool = False
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    details: str = ""
    broken_exit_code: int | None = None


def run_cmd(args, cwd=None):
    proc = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def print_result(result):
    tag = result.status
    print(f"[{tag}] {result.name}")
    if result.details:
        print(f"  {result.details}")
    if result.status == "FAIL":
        if result.returncode is not None:
            print(f"  returncode: {result.returncode}")
        out = result.stdout.strip()
        err = result.stderr.strip()
        if out:
            print("  stdout:")
            for line in out.splitlines():
                print(f"    {line}")
        if err:
            print("  stderr:")
            for line in err.splitlines():
                print(f"    {line}")


def to_jsonable(result):
    data = asdict(result)
    return data


def detect_manifest(repo_root: Path):
    candidates = []
    for pattern in ("*.yml", "*.yaml", "*.json"):
        candidates.extend(repo_root.glob(pattern))

    flatpak_dir = repo_root / "flatpak"
    if flatpak_dir.exists() and flatpak_dir.is_dir():
        for pattern in ("*.yml", "*.yaml", "*.json"):
            candidates.extend(flatpak_dir.glob(pattern))
    candidates = sorted({p.resolve() for p in candidates})

    if len(candidates) == 1:
        return candidates[0], None
    if len(candidates) == 0:
        return (
            None,
            "Kein Manifest gefunden unter ./*.yml|*.yaml|*.json oder flatpak/*.yml|*.yaml|*.json. Bitte --manifest setzen.",
        )

    listed = "\n".join(f"- {p}" for p in candidates)
    return None, f"Mehrere Manifeste gefunden. Bitte --manifest setzen:\n{listed}"


def resolve_path(value: str, repo_root: Path):
    p = Path(value)
    if p.is_absolute():
        return p
    candidate = (repo_root / p).resolve()
    if candidate.exists():
        return candidate
    return p.resolve()


def extract_app_id(manifest_path: Path):
    try:
        text = manifest_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    patterns = [
        r'^\s*(?:"?app-id"?)\s*:\s*["\']?([A-Za-z0-9._-]+)',
        r'^\s*(?:"?id"?)\s*:\s*["\']?([A-Za-z0-9._-]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.MULTILINE)
        if match:
            return match.group(1)
    return None


def find_metainfo(repo_root: Path, app_id: str | None):
    all_meta = []
    all_meta.extend(repo_root.rglob("*.metainfo.xml"))
    all_meta.extend(repo_root.rglob("*.appdata.xml"))
    all_meta = sorted({p.resolve() for p in all_meta if p.is_file()})

    if not all_meta:
        return None

    if app_id:
        pref_names = {f"{app_id}.metainfo.xml", f"{app_id}.appdata.xml"}
        preferred = [p for p in all_meta if p.name in pref_names]
        if preferred:
            return sorted(preferred)[0]

    return all_meta[0]


def is_skipped_path(path: Path):
    return any(part in WALK_SKIP_DIRS for part in path.parts)


def check_flatpak_binary():
    if shutil.which("flatpak"):
        return CheckResult(name="flatpak binary vorhanden", status="OK")
    return CheckResult(
        name="flatpak binary vorhanden",
        status="FAIL",
        hard=True,
        details="'flatpak' wurde nicht gefunden. Bitte Flatpak installieren.",
        broken_exit_code=EXIT_MISSING_BINARY,
    )


def check_builder_installed():
    rc, out, err = run_cmd(["flatpak", "info", "org.flatpak.Builder"])
    if rc == 0:
        return CheckResult(
            name="org.flatpak.Builder installiert", status="OK", stdout=out, stderr=err
        )

    fix = (
        "Fix:\n"
        "flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo\n"
        "flatpak install -y flathub org.flatpak.Builder"
    )
    return CheckResult(
        name="org.flatpak.Builder installiert",
        status="FAIL",
        hard=True,
        returncode=rc,
        stdout=out,
        stderr=err,
        details=fix,
    )


def check_manifest_lint(manifest_path: Path):
    rc, out, err = run_cmd(
        [
            "flatpak",
            "run",
            "--command=flatpak-builder-lint",
            "org.flatpak.Builder",
            "manifest",
            str(manifest_path),
        ]
    )
    if rc == 0:
        return CheckResult(
            name=f"Manifest lint ({manifest_path})",
            status="OK",
            returncode=rc,
            stdout=out,
            stderr=err,
        )
    return CheckResult(
        name=f"Manifest lint ({manifest_path})",
        status="FAIL",
        hard=True,
        returncode=rc,
        stdout=out,
        stderr=err,
    )


def check_appstream_lint(metainfo_path: Path):
    rc, out, err = run_cmd(
        [
            "flatpak",
            "run",
            "--command=flatpak-builder-lint",
            "org.flatpak.Builder",
            "appstream",
            str(metainfo_path),
        ]
    )
    if rc == 0:
        return CheckResult(
            name=f"AppStream lint ({metainfo_path})",
            status="OK",
            returncode=rc,
            stdout=out,
            stderr=err,
        )
    return CheckResult(
        name=f"AppStream lint ({metainfo_path})",
        status="FAIL",
        hard=True,
        returncode=rc,
        stdout=out,
        stderr=err,
    )


def check_repo_lint(repo_path: Path, label: str = "Repo lint"):
    rc, out, err = run_cmd(
        [
            "flatpak",
            "run",
            "--command=flatpak-builder-lint",
            "org.flatpak.Builder",
            "repo",
            str(repo_path),
        ]
    )
    if rc == 0:
        return CheckResult(
            name=f"{label} ({repo_path})", status="OK", returncode=rc, stdout=out, stderr=err
        )
    return CheckResult(
        name=f"{label} ({repo_path})",
        status="FAIL",
        hard=True,
        returncode=rc,
        stdout=out,
        stderr=err,
    )


def check_bundle_lint(bundle_path: Path):
    if not shutil.which("ostree"):
        return [
            CheckResult(
                name="ostree binary vorhanden (Bundle-Checks)",
                status="FAIL",
                hard=True,
                details="'ostree' wurde nicht gefunden, Bundle-Checks sind nicht moeglich.",
                broken_exit_code=EXIT_MISSING_BINARY,
            )
        ]

    results = []
    with tempfile.TemporaryDirectory(prefix="flathub_tester_") as td:
        temp_repo = Path(td) / "repo"

        rc_init, out_init, err_init = run_cmd(
            ["ostree", f"--repo={temp_repo}", "init", "--mode=bare-user"]
        )
        if rc_init != 0:
            results.append(
                CheckResult(
                    name="Temp OSTree Repo init",
                    status="FAIL",
                    hard=True,
                    returncode=rc_init,
                    stdout=out_init,
                    stderr=err_init,
                    broken_exit_code=EXIT_BROKEN_ENV,
                )
            )
            return results

        results.append(
            CheckResult(
                name="Temp OSTree Repo init",
                status="OK",
                returncode=rc_init,
                stdout=out_init,
                stderr=err_init,
            )
        )

        rc_imp, out_imp, err_imp = run_cmd(
            [
                "flatpak",
                "build-import-bundle",
                str(temp_repo),
                str(bundle_path),
                "--update-appstream",
            ]
        )
        if rc_imp != 0:
            results.append(
                CheckResult(
                    name=f"Bundle import ({bundle_path})",
                    status="FAIL",
                    hard=True,
                    returncode=rc_imp,
                    stdout=out_imp,
                    stderr=err_imp,
                    broken_exit_code=EXIT_BUNDLE_IMPORT_FAIL,
                )
            )
            return results

        results.append(
            CheckResult(
                name=f"Bundle import ({bundle_path})",
                status="OK",
                returncode=rc_imp,
                stdout=out_imp,
                stderr=err_imp,
            )
        )

        rc_upd, out_upd, err_upd = run_cmd(["flatpak", "build-update-repo", str(temp_repo)])
        if rc_upd == 0:
            results.append(
                CheckResult(
                    name="build-update-repo (temp)",
                    status="OK",
                    returncode=rc_upd,
                    stdout=out_upd,
                    stderr=err_upd,
                )
            )
        else:
            results.append(
                CheckResult(
                    name="build-update-repo (temp)",
                    status="WARN",
                    warning=True,
                    returncode=rc_upd,
                    stdout=out_upd,
                    stderr=err_upd,
                    details="Warn-only: build-update-repo ist fehlgeschlagen, repo lint wird trotzdem ausgefuehrt.",
                )
            )

        results.append(check_repo_lint(temp_repo, label="Bundle Repo lint"))
    return results


def check_desktop_files(repo_root: Path, app_id: str | None):
    if not shutil.which("desktop-file-validate"):
        return CheckResult(
            name="Desktop-Dateien validieren",
            status="WARN",
            warning=True,
            details="desktop-file-validate nicht gefunden (optional, kein Fail).",
        )

    all_desktops = sorted(
        [
            p.resolve()
            for p in repo_root.rglob("*.desktop")
            if p.is_file() and not is_skipped_path(p.relative_to(repo_root))
        ]
    )
    if not all_desktops:
        return CheckResult(
            name="Desktop-Dateien validieren",
            status="WARN",
            warning=True,
            details="Keine .desktop-Dateien gefunden.",
        )

    selected = all_desktops
    if app_id:
        preferred = [p for p in all_desktops if p.name == f"{app_id}.desktop"]
        if preferred:
            selected = preferred

    rc_total = 0
    out_parts = []
    err_parts = []
    for desktop in selected:
        rc, out, err = run_cmd(["desktop-file-validate", str(desktop)])
        rc_total = max(rc_total, rc)
        if out.strip():
            out_parts.append(f"[{desktop}]\n{out.strip()}")
        if err.strip():
            err_parts.append(f"[{desktop}]\n{err.strip()}")

    if rc_total == 0:
        return CheckResult(
            name=f"Desktop-Dateien validieren ({len(selected)} Datei(en))",
            status="OK",
            returncode=0,
        )

    return CheckResult(
        name=f"Desktop-Dateien validieren ({len(selected)} Datei(en))",
        status="FAIL",
        soft=True,
        returncode=rc_total,
        stdout="\n\n".join(out_parts),
        stderr="\n\n".join(err_parts),
        details="Desktop-Validierung hat Fehler gemeldet (soft fail).",
    )


def check_repo_hygiene(repo_root: Path):
    soft_fail_artifact_names = ["repo", "build", "builddir", "dist", "__pycache__"]
    warn_artifact_names = [".flatpak-builder"]

    soft_fail_found = []
    warn_found = []

    for name in soft_fail_artifact_names:
        if name != "__pycache__":
            p = repo_root / name
            if p.exists():
                soft_fail_found.append(p.resolve())

    for name in warn_artifact_names:
        p = repo_root / name
        if p.exists():
            warn_found.append(p.resolve())

    pycache_found = []
    for root, dirs, _files in os.walk(repo_root):
        root_path = Path(root)
        rel_root = root_path.relative_to(repo_root)
        dirs[:] = [d for d in dirs if d not in WALK_SKIP_DIRS]
        if is_skipped_path(rel_root):
            continue
        if root_path.name == "__pycache__":
            pycache_found.append(root_path.resolve())
    soft_fail_found.extend(pycache_found)

    large_files = []
    threshold = 50 * 1024 * 1024
    for root, dirs, files in os.walk(repo_root):
        root_path = Path(root)
        rel_root = root_path.relative_to(repo_root)
        dirs[:] = [d for d in dirs if d not in WALK_SKIP_DIRS]
        if is_skipped_path(rel_root):
            continue
        for filename in files:
            fp = root_path / filename
            try:
                size = fp.stat().st_size
            except OSError:
                continue
            if size >= threshold:
                large_files.append((fp.resolve(), size))

    details = []
    status = "OK"
    soft = False
    warning = False

    if soft_fail_found:
        status = "FAIL"
        soft = True
        details.append("Build-Artefakte gefunden (soft fail):")
        shown = 0
        for p in sorted(soft_fail_found):
            if shown >= 25:
                break
            details.append(f"- {p}")
            shown += 1
        remaining = len(soft_fail_found) - shown
        if remaining > 0:
            details.append(f"- ... und {remaining} weitere")

    if warn_found:
        if status == "OK":
            status = "WARN"
        warning = True
        details.append("Builder-Cache gefunden (Warnung):")
        for p in sorted(warn_found):
            details.append(f"- {p}")

    if large_files:
        if status == "OK":
            status = "WARN"
        warning = True
        details.append("Dateien >= 50 MiB gefunden (Warnung):")
        for p, size in sorted(large_files, key=lambda x: str(x[0]))[:25]:
            mib = size / (1024 * 1024)
            details.append(f"- {p} ({mib:.1f} MiB)")
        if len(large_files) > 25:
            details.append(f"- ... und {len(large_files) - 25} weitere")

    return CheckResult(
        name="Repo Hygiene",
        status=status,
        soft=soft,
        warning=warning,
        details="\n".join(details),
    )


def main():
    parser = argparse.ArgumentParser(description="Flathub Requirements Tester fuer ShellDeck")
    parser.add_argument("--repo-root", default=".", help="Pfad zum Repo-Root (default: .)")
    parser.add_argument("--manifest", help="Pfad zum Flatpak-Manifest")
    parser.add_argument("--repo", help="Pfad zu einem OSTree-Repo")
    parser.add_argument("--bundle", help="Pfad zu einer .flatpak Bundle-Datei")
    parser.add_argument("--json", action="store_true", help="JSON-Output fuer CI")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    if not repo_root.exists():
        result = CheckResult(
            name="Repo-Root existiert",
            status="FAIL",
            hard=True,
            details=f"Repo-Root existiert nicht: {repo_root}",
            broken_exit_code=EXIT_BROKEN_ENV,
        )
        if args.json:
            payload = {
                "repo_root": str(repo_root),
                "results": [to_jsonable(result)],
                "summary": {
                    "hard_failures": 1,
                    "soft_failures": 0,
                    "warnings": 0,
                    "broken_environment": True,
                    "exit_code": EXIT_BROKEN_ENV,
                },
            }
            print(json.dumps(payload, indent=2, ensure_ascii=True))
        else:
            print_result(result)
        return EXIT_BROKEN_ENV

    results = []

    flatpak_check = check_flatpak_binary()
    results.append(flatpak_check)

    has_flatpak = flatpak_check.status == "OK"
    builder_ok = False

    manifest_path = None
    manifest_detect_issue = None

    if args.manifest:
        manifest_path = resolve_path(args.manifest, repo_root)
        if not manifest_path.exists():
            results.append(
                CheckResult(
                    name="Manifest vorhanden",
                    status="FAIL",
                    hard=True,
                    details=f"Manifest wurde nicht gefunden: {manifest_path}",
                )
            )
            manifest_path = None
    else:
        manifest_path, manifest_detect_issue = detect_manifest(repo_root)

    app_id = extract_app_id(manifest_path) if manifest_path else None

    if has_flatpak:
        builder_check = check_builder_installed()
        results.append(builder_check)
        builder_ok = builder_check.status == "OK"

    run_manifest_related = bool(manifest_path)
    strict_manifest_required = not args.repo and not args.bundle

    if not args.manifest and manifest_detect_issue:
        if strict_manifest_required:
            results.append(
                CheckResult(
                    name="Manifest Auto-Erkennung",
                    status="FAIL",
                    hard=True,
                    details=manifest_detect_issue,
                )
            )
        else:
            results.append(
                CheckResult(
                    name="Manifest Auto-Erkennung",
                    status="WARN",
                    warning=True,
                    details=f"{manifest_detect_issue} Manifest/AppStream-Checks werden uebersprungen.",
                )
            )

    if run_manifest_related:
        if has_flatpak and builder_ok:
            results.append(check_manifest_lint(manifest_path))

            metainfo_path = find_metainfo(repo_root, app_id)
            if metainfo_path:
                results.append(check_appstream_lint(metainfo_path))
            else:
                results.append(
                    CheckResult(
                        name="AppStream lint",
                        status="FAIL",
                        hard=True,
                        details="Keine .metainfo.xml/.appdata.xml gefunden.",
                    )
                )
        elif has_flatpak and not builder_ok:
            results.append(
                CheckResult(
                    name="Manifest/AppStream lint",
                    status="SKIP",
                    warning=True,
                    details="Uebersprungen, weil org.flatpak.Builder fehlt.",
                )
            )

    if args.repo:
        repo_path = resolve_path(args.repo, repo_root)
        if not repo_path.exists():
            results.append(
                CheckResult(
                    name="Repo-Pfad vorhanden",
                    status="FAIL",
                    hard=True,
                    details=f"Repo wurde nicht gefunden: {repo_path}",
                )
            )
        elif has_flatpak and builder_ok:
            results.append(check_repo_lint(repo_path))
        elif has_flatpak and not builder_ok:
            results.append(
                CheckResult(
                    name="Repo lint",
                    status="SKIP",
                    warning=True,
                    details="Uebersprungen, weil org.flatpak.Builder fehlt.",
                )
            )

    if args.bundle:
        bundle_path = resolve_path(args.bundle, repo_root)
        if not bundle_path.exists():
            results.append(
                CheckResult(
                    name="Bundle-Pfad vorhanden",
                    status="FAIL",
                    hard=True,
                    details=f"Bundle wurde nicht gefunden: {bundle_path}",
                )
            )
        elif has_flatpak and builder_ok:
            results.extend(check_bundle_lint(bundle_path))
        elif has_flatpak and not builder_ok:
            results.append(
                CheckResult(
                    name="Bundle lint",
                    status="SKIP",
                    warning=True,
                    details="Uebersprungen, weil org.flatpak.Builder fehlt.",
                )
            )

    if manifest_path:
        results.append(check_desktop_files(repo_root, app_id))

    results.append(check_repo_hygiene(repo_root))

    hard_failures = 0
    soft_failures = 0
    warnings = 0
    broken_code = None

    for result in results:
        if result.hard and result.status == "FAIL":
            hard_failures += 1
        if result.soft and result.status == "FAIL":
            soft_failures += 1
        if result.warning or result.status in ("WARN", "SKIP"):
            warnings += 1
        if result.broken_exit_code:
            if broken_code is None:
                broken_code = result.broken_exit_code
            else:
                broken_code = min(broken_code, result.broken_exit_code)

    if args.json:
        exit_code = EXIT_OK
        if broken_code is not None:
            exit_code = broken_code
        elif hard_failures > 0:
            exit_code = EXIT_HARD_FAIL

        payload = {
            "repo_root": str(repo_root),
            "results": [to_jsonable(r) for r in results],
            "summary": {
                "hard_failures": hard_failures,
                "soft_failures": soft_failures,
                "warnings": warnings,
                "broken_environment": broken_code is not None,
                "exit_code": exit_code,
            },
        }
        print(json.dumps(payload, indent=2, ensure_ascii=True))
        return exit_code

    for result in results:
        print_result(result)

    print("\nSummary")
    print(f"- Harte Fehler: {hard_failures}")
    print(f"- Nur Hygiene/Soft-Fails: {soft_failures}")
    print(f"- Warnings/Skips: {warnings}")

    if broken_code is not None:
        print(f"- Broken environment erkannt (Exit-Code {broken_code})")
        return broken_code

    if hard_failures > 0:
        return EXIT_HARD_FAIL
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
