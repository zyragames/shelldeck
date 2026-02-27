from __future__ import annotations

from dataclasses import dataclass
import ast
import os
from importlib import metadata
from pathlib import Path
import platform
import re
import sys

from PySide6 import QtCore, QtGui, QtWidgets

from ... import __version__
from ...data.db import get_default_db_path
from ..sidebar import KOFI_FALLBACK_URL, KOFI_LOCAL_IMAGE, KOFI_PRIMARY_URL


@dataclass(frozen=True)
class DependencyInfo:
    name: str
    version: str
    source: str


class AboutDialog(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About ShellDeck")
        self.setModal(True)
        self.setMinimumSize(720, 520)
        self.resize(820, 600)

        self._app_version = self._resolve_app_version()
        self._build_info = self._resolve_build_info()
        self._dependencies = self._load_dependencies()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addLayout(self._build_header())

        tabs = QtWidgets.QTabWidget(self)
        tabs.setDocumentMode(True)
        tabs.setTabPosition(QtWidgets.QTabWidget.TabPosition.North)
        tabs.addTab(self._build_about_tab(), "About")
        tabs.addTab(self._build_libraries_tab(), "Libraries")
        tabs.addTab(self._build_system_tab(), "System")
        layout.addWidget(tabs, 1)

        layout.addLayout(self._build_buttons())

    def _build_header(self) -> QtWidgets.QLayout:
        header = QtWidgets.QHBoxLayout()
        header.setSpacing(12)

        icon_label = QtWidgets.QLabel()
        icon = self._resolve_app_icon()
        if not icon.isNull():
            icon_label.setPixmap(icon.pixmap(64, 64))
        icon_label.setFixedSize(72, 72)
        icon_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        text_layout = QtWidgets.QVBoxLayout()
        name_label = QtWidgets.QLabel("ShellDeck")
        name_label.setStyleSheet("font-size: 20px; font-weight: 600;")
        version_label = QtWidgets.QLabel(f"Version {self._app_version}")
        tagline = QtWidgets.QLabel("Linux-first desktop app for organizing SSH workspaces.")
        tagline.setStyleSheet("color: #94a3b8;")

        text_layout.addWidget(name_label)
        text_layout.addWidget(version_label)
        text_layout.addWidget(tagline)
        text_layout.addStretch(1)

        header.addWidget(icon_label)
        header.addLayout(text_layout, 1)
        return header

    def _resolve_app_icon(self) -> QtGui.QIcon:
        icon = self.windowIcon()
        parent_widget = self.parentWidget()
        if icon.isNull() and parent_widget is not None:
            icon = parent_widget.windowIcon()
        if icon.isNull():
            icon = QtWidgets.QApplication.windowIcon()
        return icon

    def _build_about_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        version_group = QtWidgets.QGroupBox("Version")
        version_layout = QtWidgets.QFormLayout(version_group)
        version_layout.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        version_layout.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        version_layout.addRow("App version", QtWidgets.QLabel(self._app_version))
        if self._build_info:
            version_layout.addRow("Build", QtWidgets.QLabel(self._build_info))

        links_group = QtWidgets.QGroupBox("Links")
        links_layout = QtWidgets.QVBoxLayout(links_group)
        links_layout.setSpacing(6)
        links_layout.addWidget(
            self._build_kofi_button(), alignment=QtCore.Qt.AlignmentFlag.AlignLeft
        )
        links_layout.addStretch(1)

        layout.addWidget(version_group)
        layout.addWidget(links_group)
        layout.addStretch(1)
        return page

    def _build_libraries_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        runtime_group = QtWidgets.QGroupBox("Runtime")
        runtime_layout = QtWidgets.QFormLayout(runtime_group)
        runtime_layout.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        runtime_layout.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        runtime_layout.addRow("Python", QtWidgets.QLabel(platform.python_version()))
        runtime_layout.addRow("Qt", QtWidgets.QLabel(QtCore.qVersion()))
        runtime_layout.addRow("PySide6", QtWidgets.QLabel(self._package_version("PySide6")))
        runtime_layout.addRow("termqt", QtWidgets.QLabel(self._package_version("termqt")))

        deps_group = QtWidgets.QGroupBox("Dependencies")
        deps_layout = QtWidgets.QVBoxLayout(deps_group)
        deps_layout.setSpacing(6)
        table = QtWidgets.QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["Name", "Version", "Source"])
        table.setRowCount(len(self._dependencies))
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)

        for row, dep in enumerate(self._dependencies):
            table.setItem(row, 0, QtWidgets.QTableWidgetItem(dep.name))
            table.setItem(row, 1, QtWidgets.QTableWidgetItem(dep.version))
            table.setItem(row, 2, QtWidgets.QTableWidgetItem(dep.source))

        table.sortItems(0, QtCore.Qt.SortOrder.AscendingOrder)
        deps_layout.addWidget(table)

        layout.addWidget(runtime_group)
        layout.addWidget(deps_group, 1)
        return page

    def _build_system_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        system_group = QtWidgets.QGroupBox("System")
        system_layout = QtWidgets.QFormLayout(system_group)
        system_layout.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        system_layout.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        system_layout.addRow(
            "OS",
            QtWidgets.QLabel(f"{platform.system()} {platform.release()} ({platform.version()})"),
        )
        system_layout.addRow("Python executable", QtWidgets.QLabel(sys.executable))
        system_layout.addRow("Settings path", QtWidgets.QLabel(QtCore.QSettings().fileName()))
        system_layout.addRow("Data path", QtWidgets.QLabel(str(get_default_db_path())))
        log_path = self._log_path()
        system_layout.addRow("Log path", QtWidgets.QLabel(str(log_path)))

        layout.addWidget(system_group)

        if log_path.parent.exists():
            open_logs = QtWidgets.QPushButton("Open Logs Folder")
            open_logs.setToolTip("Open the folder containing shelldeck.log")
            open_logs.clicked.connect(lambda: self._open_folder(log_path.parent))
            layout.addWidget(open_logs, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)

        layout.addStretch(1)
        return page

    def _build_buttons(self) -> QtWidgets.QLayout:
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)

        copy_button = QtWidgets.QPushButton("Copy Debug Info")
        copy_button.setToolTip("Copy diagnostic info to clipboard")
        copy_button.clicked.connect(self._copy_debug_info)
        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.accept)

        row.addWidget(copy_button)
        row.addWidget(close_button)
        return row

    def _copy_debug_info(self) -> None:
        text = self._build_debug_info()
        QtGui.QGuiApplication.clipboard().setText(text)

    def _build_debug_info(self) -> str:
        lines = [
            f"ShellDeck {self._app_version}",
            (
                f"Python {platform.python_version()} | Qt {QtCore.qVersion()} | "
                f"PySide6 {self._package_version('PySide6')}"
            ),
            f"OS {platform.system()} {platform.release()} ({platform.version()})",
            f"Executable {sys.executable}",
            f"Settings {QtCore.QSettings().fileName()}",
            f"Data {get_default_db_path()}",
            f"Logs {self._log_path()}",
        ]
        if self._build_info:
            lines.insert(1, f"Build {self._build_info}")
        lines.append("")
        lines.append("Dependencies:")
        for dep in sorted(self._dependencies, key=lambda item: item.name.lower()):
            lines.append(f"- {dep.name} {dep.version}")
        return "\n".join(lines)

    def _build_kofi_button(self) -> QtWidgets.QToolButton:
        button = QtWidgets.QToolButton()
        button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        button.setAutoRaise(True)
        button.setStyleSheet(
            "QToolButton { padding: 0px; margin: 0px; border: none; background: transparent; }"
            "QToolButton:hover { background: transparent; }"
            "QToolButton:pressed { background: transparent; }"
            "QToolButton:focus { outline: none; }"
        )
        button.clicked.connect(self._open_kofi)

        badge_width = 120
        badge_pixmap = QtGui.QPixmap(str(KOFI_LOCAL_IMAGE))
        if not badge_pixmap.isNull():
            scaled = badge_pixmap.scaledToWidth(
                badge_width,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            button.setIcon(QtGui.QIcon(scaled))
            button.setIconSize(scaled.size())
            button.setFixedSize(scaled.size())
        else:
            button.setText("Support on Ko-fi")
        return button

    def _open_kofi(self) -> None:
        link_target = KOFI_PRIMARY_URL or KOFI_FALLBACK_URL
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(link_target))

    def _resolve_app_version(self) -> str:
        version = __version__
        if version:
            return version
        return self._package_version("shelldeck")

    def _resolve_build_info(self) -> str | None:
        build = os.environ.get("SHELLDECK_BUILD", "").strip()
        commit = os.environ.get("SHELLDECK_COMMIT", "").strip()
        branch = os.environ.get("SHELLDECK_BRANCH", "").strip()
        parts = [item for item in [build, commit, branch] if item]
        if not parts:
            return None
        return " / ".join(parts)

    def _load_dependencies(self) -> list[DependencyInfo]:
        dependencies: list[DependencyInfo] = []
        root = self._find_repo_root(Path(__file__).resolve())
        if root is None:
            return dependencies

        pyproject_path = root / "pyproject.toml"
        if pyproject_path.exists():
            deps = self._parse_pyproject_dependencies(pyproject_path)
            dependencies.extend(self._resolve_dependencies(deps, "pyproject.toml"))

        for req_path in sorted(root.glob("requirements*.txt")):
            reqs = self._parse_requirements(req_path)
            dependencies.extend(self._resolve_dependencies(reqs, req_path.name))

        return self._dedupe_dependencies(dependencies)

    def _parse_pyproject_dependencies(self, path: Path) -> list[str]:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return []
        return self._extract_toml_array(content, "dependencies", section="project")

    def _parse_requirements(self, path: Path) -> list[str]:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return []
        requirements = []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            requirements.append(stripped)
        return requirements

    def _resolve_dependencies(self, specs: list[str], source: str) -> list[DependencyInfo]:
        resolved: list[DependencyInfo] = []
        for spec in specs:
            name = self._parse_requirement_name(spec)
            if not name:
                continue
            resolved.append(
                DependencyInfo(
                    name=name,
                    version=self._package_version(name),
                    source=source,
                )
            )
        return resolved

    def _dedupe_dependencies(self, deps: list[DependencyInfo]) -> list[DependencyInfo]:
        seen: dict[str, DependencyInfo] = {}
        for dep in deps:
            key = dep.name.lower()
            if key not in seen:
                seen[key] = dep
        return list(seen.values())

    def _parse_requirement_name(self, spec: str) -> str:
        match = re.match(r"^[A-Za-z0-9_.-]+", spec.strip())
        return match.group(0) if match else ""

    def _extract_toml_array(self, content: str, key: str, section: str) -> list[str]:
        in_section = False
        collecting = False
        buffer: list[str] = []
        header = f"[{section}]"
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                in_section = stripped == header
                if not in_section:
                    collecting = False
                    buffer = []
                continue
            if not in_section:
                continue
            if not collecting and stripped.startswith(f"{key}"):
                parts = line.split("=", 1)
                if len(parts) < 2:
                    continue
                remainder = parts[1].strip()
                if "[" in remainder:
                    buffer.append(remainder)
                    if "]" in remainder:
                        collecting = False
                        break
                    collecting = True
                continue
            if collecting:
                buffer.append(line)
                if "]" in line:
                    collecting = False
                    break
        if not buffer:
            return []
        raw = "\n".join(buffer)
        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1:
            return []
        try:
            value = ast.literal_eval(raw[start : end + 1])
        except (SyntaxError, ValueError):
            return []
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str)]

    def _package_version(self, package: str) -> str:
        try:
            return metadata.version(package)
        except metadata.PackageNotFoundError:
            return "unknown"

    def _find_repo_root(self, start: Path) -> Path | None:
        for parent in [start] + list(start.parents):
            if (parent / "pyproject.toml").exists():
                return parent
        return None

    def _log_path(self) -> Path:
        cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        return cache_root / "shelldeck" / "shelldeck.log"

    def _open_folder(self, path: Path) -> None:
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))
