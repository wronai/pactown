"""Target platform definitions for markpact projects.

Markpact files can target different platforms:
- web: online service (default, existing behavior)
- desktop: desktop application (Electron, Tauri, PyInstaller, Tkinter)
- mobile: mobile application (Capacitor, React Native, Flutter, Kivy)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import yaml


class TargetPlatform(str, Enum):
    """Target platform for a markpact project."""

    WEB = "web"
    DESKTOP = "desktop"
    MOBILE = "mobile"


class DesktopFramework(str, Enum):
    """Desktop application frameworks."""

    ELECTRON = "electron"
    TAURI = "tauri"
    PYINSTALLER = "pyinstaller"
    TKINTER = "tkinter"
    PYQT = "pyqt"
    FLUTTER = "flutter"


class MobileFramework(str, Enum):
    """Mobile application frameworks."""

    CAPACITOR = "capacitor"
    REACT_NATIVE = "react-native"
    FLUTTER = "flutter"
    KIVY = "kivy"


class WebFramework(str, Enum):
    """Web application frameworks (informational)."""

    FASTAPI = "fastapi"
    FLASK = "flask"
    EXPRESS = "express"
    NEXT = "next"
    REACT = "react"
    VUE = "vue"


# ---------------------------------------------------------------------------
# Framework metadata: default deps, scaffolding hints, build commands
# ---------------------------------------------------------------------------

@dataclass
class FrameworkMeta:
    """Metadata about a framework used for scaffolding and building."""

    name: str
    platform: TargetPlatform
    language: str  # python | javascript | typescript | dart | rust
    default_deps: list[str] = field(default_factory=list)
    default_dev_deps: list[str] = field(default_factory=list)
    default_build_cmd: str = ""
    default_run_cmd: str = ""
    scaffold_files: dict[str, str] = field(default_factory=dict)
    needs_node: bool = False
    needs_python: bool = False
    artifact_patterns: list[str] = field(default_factory=list)


FRAMEWORK_REGISTRY: dict[str, FrameworkMeta] = {
    # Desktop frameworks
    "electron": FrameworkMeta(
        name="electron",
        platform=TargetPlatform.DESKTOP,
        language="javascript",
        default_deps=["electron"],
        default_dev_deps=["electron-builder"],
        default_build_cmd="npx electron-builder --linux --windows --mac",
        default_run_cmd="npx electron .",
        needs_node=True,
        artifact_patterns=["dist/*.AppImage", "dist/*.exe", "dist/*.dmg"],
    ),
    "tauri": FrameworkMeta(
        name="tauri",
        platform=TargetPlatform.DESKTOP,
        language="rust",
        default_deps=["@tauri-apps/api"],
        default_dev_deps=["@tauri-apps/cli"],
        default_build_cmd="npx tauri build",
        default_run_cmd="npx tauri dev",
        needs_node=True,
        artifact_patterns=["src-tauri/target/release/bundle/**"],
    ),
    "pyinstaller": FrameworkMeta(
        name="pyinstaller",
        platform=TargetPlatform.DESKTOP,
        language="python",
        default_deps=["pyinstaller"],
        default_build_cmd="pyinstaller --onefile --windowed main.py",
        default_run_cmd="python main.py",
        needs_python=True,
        artifact_patterns=["dist/*"],
    ),
    "tkinter": FrameworkMeta(
        name="tkinter",
        platform=TargetPlatform.DESKTOP,
        language="python",
        default_deps=[],
        default_build_cmd="pyinstaller --onefile --windowed main.py",
        default_run_cmd="python main.py",
        needs_python=True,
        artifact_patterns=["dist/*"],
    ),
    "pyqt": FrameworkMeta(
        name="pyqt",
        platform=TargetPlatform.DESKTOP,
        language="python",
        default_deps=["PyQt6"],
        default_build_cmd="pyinstaller --onefile --windowed main.py",
        default_run_cmd="python main.py",
        needs_python=True,
        artifact_patterns=["dist/*"],
    ),
    "flutter-desktop": FrameworkMeta(
        name="flutter",
        platform=TargetPlatform.DESKTOP,
        language="dart",
        default_build_cmd="flutter build linux",
        default_run_cmd="flutter run -d linux",
        artifact_patterns=["build/linux/**"],
    ),
    # Mobile frameworks
    "capacitor": FrameworkMeta(
        name="capacitor",
        platform=TargetPlatform.MOBILE,
        language="javascript",
        default_deps=["@capacitor/core", "@capacitor/cli"],
        default_dev_deps=["@capacitor/android", "@capacitor/ios"],
        default_build_cmd="npx cap sync && npx cap build android",
        default_run_cmd="npx cap run android",
        needs_node=True,
        artifact_patterns=["android/app/build/outputs/apk/**", "ios/App/build/**"],
    ),
    "react-native": FrameworkMeta(
        name="react-native",
        platform=TargetPlatform.MOBILE,
        language="javascript",
        default_deps=["react-native"],
        default_dev_deps=["@react-native-community/cli"],
        default_build_cmd="npx react-native build-android --mode=release",
        default_run_cmd="npx react-native run-android",
        needs_node=True,
        artifact_patterns=["android/app/build/outputs/apk/**"],
    ),
    "flutter-mobile": FrameworkMeta(
        name="flutter",
        platform=TargetPlatform.MOBILE,
        language="dart",
        default_build_cmd="flutter build apk",
        default_run_cmd="flutter run",
        artifact_patterns=["build/app/outputs/flutter-apk/**"],
    ),
    "kivy": FrameworkMeta(
        name="kivy",
        platform=TargetPlatform.MOBILE,
        language="python",
        default_deps=["kivy", "buildozer"],
        default_build_cmd="buildozer android debug",
        default_run_cmd="python main.py",
        needs_python=True,
        artifact_patterns=["bin/*.apk"],
    ),
}


def get_framework_meta(name: str) -> Optional[FrameworkMeta]:
    """Look up framework metadata by name (case-insensitive)."""
    key = (name or "").strip().lower()
    return FRAMEWORK_REGISTRY.get(key)


def list_frameworks(platform: Optional[TargetPlatform] = None) -> list[FrameworkMeta]:
    """List all known frameworks, optionally filtered by platform."""
    if platform is None:
        return list(FRAMEWORK_REGISTRY.values())
    return [f for f in FRAMEWORK_REGISTRY.values() if f.platform == platform]


# ---------------------------------------------------------------------------
# TargetConfig – parsed from markpact:target block
# ---------------------------------------------------------------------------

@dataclass
class TargetConfig:
    """Parsed target configuration from a markpact:target block."""

    platform: TargetPlatform = TargetPlatform.WEB
    framework: Optional[str] = None
    targets: list[str] = field(default_factory=list)  # e.g. ["android", "ios", "linux", "windows"]
    app_name: Optional[str] = None
    app_id: Optional[str] = None  # e.g. com.example.myapp
    app_version: Optional[str] = None
    icon: Optional[str] = None
    window_width: Optional[int] = None
    window_height: Optional[int] = None
    fullscreen: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_yaml_body(cls, body: str) -> "TargetConfig":
        """Parse a YAML markpact:target block body into TargetConfig."""
        try:
            data = yaml.safe_load(body)
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "TargetConfig":
        """Create TargetConfig from a dictionary."""
        platform_str = str(data.get("platform", "web")).strip().lower()
        try:
            platform = TargetPlatform(platform_str)
        except ValueError:
            platform = TargetPlatform.WEB

        framework = data.get("framework")
        if framework:
            framework = str(framework).strip().lower()

        raw_targets = data.get("targets", [])
        if isinstance(raw_targets, str):
            raw_targets = [t.strip() for t in raw_targets.split(",") if t.strip()]
        elif not isinstance(raw_targets, list):
            raw_targets = []
        targets = [str(t).strip().lower() for t in raw_targets]

        known_keys = {
            "platform", "framework", "targets", "app_name", "app_id",
            "app_version", "icon", "window_width", "window_height", "fullscreen",
        }
        extra = {k: v for k, v in data.items() if k not in known_keys}

        return cls(
            platform=platform,
            framework=framework,
            targets=targets,
            app_name=data.get("app_name"),
            app_id=data.get("app_id"),
            app_version=data.get("app_version"),
            icon=data.get("icon"),
            window_width=_to_int(data.get("window_width")),
            window_height=_to_int(data.get("window_height")),
            fullscreen=bool(data.get("fullscreen", False)),
            extra=extra,
        )

    @property
    def framework_meta(self) -> Optional[FrameworkMeta]:
        """Look up the FrameworkMeta for this config's framework."""
        if not self.framework:
            return None
        return get_framework_meta(self.framework)

    @property
    def is_web(self) -> bool:
        return self.platform == TargetPlatform.WEB

    @property
    def is_desktop(self) -> bool:
        return self.platform == TargetPlatform.DESKTOP

    @property
    def is_mobile(self) -> bool:
        return self.platform == TargetPlatform.MOBILE

    @property
    def is_buildable(self) -> bool:
        """Desktop and mobile targets produce build artifacts."""
        return self.platform in (TargetPlatform.DESKTOP, TargetPlatform.MOBILE)

    @property
    def needs_port(self) -> bool:
        """Only web targets need a port."""
        return self.platform == TargetPlatform.WEB

    def effective_build_targets(self) -> list[str]:
        """Return explicit targets or sensible defaults for the platform."""
        if self.targets:
            return self.targets
        if self.platform == TargetPlatform.DESKTOP:
            return ["linux"]
        if self.platform == TargetPlatform.MOBILE:
            return ["android"]
        return []


def _to_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Infer target from markpact blocks (heuristic fallback)
# ---------------------------------------------------------------------------

_DESKTOP_HINTS = {
    "electron", "tauri", "pyinstaller", "tkinter", "pyqt", "pyqt6", "pyqt5",
    "pyside6", "pyside2", "wxpython", "kivy", "toga", "flet",
}

_MOBILE_HINTS = {
    "capacitor", "@capacitor/core", "react-native", "expo", "buildozer",
    "@react-native-community/cli", "flutter",
}


def infer_target_from_deps(deps: list[str]) -> TargetPlatform:
    """Guess the target platform from dependency names."""
    dep_names = set()
    for d in deps:
        raw = d.strip()
        # Handle npm scoped packages: keep @scope/name intact
        if raw.startswith("@"):
            # Strip trailing version specifier: @scope/name@1.0 or @scope/name>=1
            name = re.split(r"(?<!/)[@<>=!~\[]", raw[1:], maxsplit=1)[0].strip().lower()
            name = "@" + name
        else:
            name = re.split(r"[<>=!~\[@]", raw, maxsplit=1)[0].strip().lower()
        dep_names.add(name)

    if dep_names & _MOBILE_HINTS:
        return TargetPlatform.MOBILE
    if dep_names & _DESKTOP_HINTS:
        return TargetPlatform.DESKTOP
    return TargetPlatform.WEB
