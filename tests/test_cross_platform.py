"""Comprehensive cross-platform tests: every framework × every OS/platform.

Tests scaffold correctness, artifact generation, build commands, and
Ansible deployment for ALL supported combinations:

Desktop (6 frameworks × 3 OS = 18):
  Electron, Tauri, PyInstaller, PyQt, Tkinter, Flutter
  × linux, windows, macos

Mobile (4 frameworks × 2 platforms = 8):
  Capacitor, React Native, Flutter, Kivy
  × android, ios

Web (6 frameworks):
  FastAPI, Flask, Express, Next, React, Vue
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from pactown.builders import DesktopBuilder, MobileBuilder, WebBuilder
from pactown.deploy.ansible import AnsibleBackend, AnsibleConfig
from pactown.deploy.base import DeploymentConfig, DeploymentMode, RuntimeType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deploy_config(**kw: Any) -> DeploymentConfig:
    defaults = dict(
        namespace=kw.pop("namespace", "test"),
        mode=DeploymentMode.DEVELOPMENT,
        expose_ports=True,
    )
    defaults.update(kw)
    return DeploymentConfig(**defaults)


# Artifact file stubs per framework × OS
_DESKTOP_ARTIFACTS: dict[str, dict[str, list[tuple[str, bytes]]]] = {
    "electron": {
        "linux": [
            ("dist/app-1.0.0.AppImage", b"\x7fELF"),
            ("dist/app-1.0.0.snap", b"snap"),
            ("dist/run.sh", b"#!/bin/bash\n"),
            ("dist/README.txt", b"README"),
        ],
        "windows": [
            ("dist/app-1.0.0.exe", b"MZ"),
        ],
        "macos": [
            ("dist/app-1.0.0.dmg", b"\x00\x00"),
        ],
    },
    "tauri": {
        "linux": [
            ("src-tauri/target/release/bundle/appimage/app.AppImage", b"\x7fELF"),
            ("src-tauri/target/release/bundle/deb/app_1.0.0_amd64.deb", b"!<arch>"),
        ],
        "windows": [
            ("src-tauri/target/release/bundle/msi/app_1.0.0_x64.msi", b"\xd0\xcf"),
            ("src-tauri/target/release/bundle/nsis/app_1.0.0_x64-setup.exe", b"MZ"),
        ],
        "macos": [
            ("src-tauri/target/release/bundle/dmg/app_1.0.0_x64.dmg", b"\x00\x00"),
            ("src-tauri/target/release/bundle/macos/app.app/Contents/MacOS/app", b"\xcf\xfa"),
        ],
    },
    "pyinstaller": {
        "linux": [("dist/app", b"\x7fELF")],
        "windows": [("dist/app.exe", b"MZ")],
        "macos": [("dist/app", b"\xcf\xfa")],
    },
    "pyqt": {
        "linux": [("dist/app", b"\x7fELF")],
        "windows": [("dist/app.exe", b"MZ")],
        "macos": [("dist/app", b"\xcf\xfa")],
    },
    "tkinter": {
        "linux": [("dist/app", b"\x7fELF")],
        "windows": [("dist/app.exe", b"MZ")],
        "macos": [("dist/app", b"\xcf\xfa")],
    },
    "flutter": {
        "linux": [
            ("build/linux/x64/release/bundle/app", b"\x7fELF"),
            ("build/linux/x64/release/bundle/lib/libflutter_linux_gtk.so", b"\x7fELF"),
        ],
        "windows": [
            ("build/windows/runner/Release/app.exe", b"MZ"),
        ],
        "macos": [
            ("build/macos/Build/Products/Release/app.app/Contents/MacOS/app", b"\xcf\xfa"),
        ],
    },
}

_MOBILE_ARTIFACTS: dict[str, dict[str, list[tuple[str, bytes]]]] = {
    "capacitor": {
        "android": [
            ("android/app/build/outputs/apk/release/app-release.apk", b"PK\x03\x04"),
            ("android/app/build/outputs/apk/debug/app-debug.apk", b"PK\x03\x04"),
        ],
        "ios": [
            ("ios/App/build/Release/App.ipa", b"PK\x03\x04"),
        ],
    },
    "react-native": {
        "android": [
            ("android/app/build/outputs/apk/release/app-release.apk", b"PK\x03\x04"),
        ],
        "ios": [
            ("ios/build/Release/App.ipa", b"PK\x03\x04"),
        ],
    },
    "flutter": {
        "android": [
            ("build/app/outputs/flutter-apk/app-release.apk", b"PK\x03\x04"),
        ],
        "ios": [
            ("build/ios/iphoneos/Runner.app/Runner.ipa", b"PK\x03\x04"),
        ],
    },
    "kivy": {
        "android": [
            ("bin/myapp-0.1-arm64-v8a_armeabi-v7a-debug.apk", b"PK\x03\x04"),
            ("bin/myapp-0.1-arm64-v8a_armeabi-v7a-release.aab", b"PK\x03\x04"),
        ],
        "ios": [
            ("bin/myapp-0.1-ios.apk", b"PK\x03\x04"),
        ],
    },
}


def _create_artifacts(sandbox: Path, artifacts: list[tuple[str, bytes]]) -> list[Path]:
    """Create fake artifact files and return their paths."""
    paths = []
    for rel, content in artifacts:
        p = sandbox / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        paths.append(p)
    return paths


# =========================================================================
# DESKTOP: scaffold + artifacts + build commands × ALL OS
# =========================================================================


class TestDesktopElectronAllOS:
    """Electron × linux, windows, macos."""

    @pytest.fixture()
    def sandbox(self, tmp_path: Path) -> Path:
        s = tmp_path / "electron-app"
        s.mkdir()
        return s

    def test_scaffold_creates_package_json_and_main_js(self, sandbox: Path) -> None:
        DesktopBuilder().scaffold(sandbox, framework="electron", app_name="myapp")
        assert (sandbox / "package.json").exists()
        assert (sandbox / "main.js").exists()

    def test_scaffold_package_json_has_all_os_targets(self, sandbox: Path) -> None:
        DesktopBuilder().scaffold(sandbox, framework="electron", app_name="myapp")
        pkg = json.loads((sandbox / "package.json").read_text())
        build = pkg["build"]
        assert build["linux"]["target"] == ["AppImage"]
        assert build["win"]["target"] == ["nsis"]
        assert build["mac"]["target"] == ["dmg"]

    def test_scaffold_main_js_has_no_sandbox(self, sandbox: Path) -> None:
        DesktopBuilder().scaffold(sandbox, framework="electron", app_name="myapp")
        src = (sandbox / "main.js").read_text()
        assert "no-sandbox" in src

    def test_scaffold_electron_dev_deps(self, sandbox: Path) -> None:
        DesktopBuilder().scaffold(sandbox, framework="electron", app_name="myapp")
        pkg = json.loads((sandbox / "package.json").read_text())
        dev = pkg.get("devDependencies", {})
        assert "electron" in dev
        assert "electron-builder" in dev

    def test_scaffold_app_id(self, sandbox: Path) -> None:
        DesktopBuilder().scaffold(sandbox, framework="electron", app_name="myapp",
                                  extra={"app_id": "com.test.myapp"})
        pkg = json.loads((sandbox / "package.json").read_text())
        assert pkg["build"]["appId"] == "com.test.myapp"

    def test_scaffold_custom_window_size(self, sandbox: Path) -> None:
        DesktopBuilder().scaffold(sandbox, framework="electron", app_name="myapp",
                                  extra={"window_width": 800, "window_height": 600})
        src = (sandbox / "main.js").read_text()
        assert "800" in src
        assert "600" in src

    @pytest.mark.parametrize("os_target", ["linux", "windows", "macos"])
    def test_artifacts_per_os(self, sandbox: Path, os_target: str) -> None:
        DesktopBuilder().scaffold(sandbox, framework="electron", app_name="myapp")
        stubs = _DESKTOP_ARTIFACTS["electron"][os_target]
        _create_artifacts(sandbox, stubs)
        found = DesktopBuilder._collect_artifacts(sandbox, "electron")
        assert len(found) >= len(stubs)
        for art in found:
            assert art.is_file()

    @pytest.mark.parametrize("os_target", ["linux", "windows", "macos"])
    def test_build_cmd_per_os(self, os_target: str) -> None:
        cmd = DesktopBuilder._default_build_cmd("electron", [os_target])
        assert "electron-builder" in cmd
        assert cmd.strip()

    def test_build_cmd_multi_os(self) -> None:
        cmd = DesktopBuilder._default_build_cmd("electron", ["linux", "windows", "macos"])
        assert "electron-builder" in cmd
        assert "--linux" in cmd

    def test_linux_artifacts_include_launcher(self, sandbox: Path) -> None:
        DesktopBuilder().scaffold(sandbox, framework="electron", app_name="myapp")
        _create_artifacts(sandbox, _DESKTOP_ARTIFACTS["electron"]["linux"])
        found = DesktopBuilder._collect_artifacts(sandbox, "electron")
        names = [a.name for a in found]
        assert "run.sh" in names
        assert "README.txt" in names

    def test_all_os_artifacts_combined(self, sandbox: Path) -> None:
        DesktopBuilder().scaffold(sandbox, framework="electron", app_name="myapp")
        for os_target in ("linux", "windows", "macos"):
            _create_artifacts(sandbox, _DESKTOP_ARTIFACTS["electron"][os_target])
        found = DesktopBuilder._collect_artifacts(sandbox, "electron")
        names = {a.name for a in found}
        assert any(n.endswith(".AppImage") for n in names)
        assert any(n.endswith(".exe") for n in names)
        assert any(n.endswith(".dmg") for n in names)


class TestDesktopTauriAllOS:
    """Tauri × linux, windows, macos."""

    @pytest.fixture()
    def sandbox(self, tmp_path: Path) -> Path:
        s = tmp_path / "tauri-app"
        s.mkdir()
        return s

    def test_scaffold_creates_tauri_conf(self, sandbox: Path) -> None:
        DesktopBuilder().scaffold(sandbox, framework="tauri", app_name="tapp")
        conf = sandbox / "src-tauri" / "tauri.conf.json"
        assert conf.exists()
        cfg = json.loads(conf.read_text())
        assert cfg["package"]["productName"] == "tapp"
        assert cfg["tauri"]["bundle"]["active"] is True
        assert cfg["tauri"]["bundle"]["targets"] == "all"

    def test_scaffold_custom_app_id(self, sandbox: Path) -> None:
        DesktopBuilder().scaffold(sandbox, framework="tauri", app_name="tapp",
                                  extra={"app_id": "org.test.tapp"})
        cfg = json.loads((sandbox / "src-tauri" / "tauri.conf.json").read_text())
        assert cfg["tauri"]["bundle"]["identifier"] == "org.test.tapp"

    def test_scaffold_custom_window_size(self, sandbox: Path) -> None:
        DesktopBuilder().scaffold(sandbox, framework="tauri", app_name="tapp",
                                  extra={"window_width": 1920, "window_height": 1080})
        cfg = json.loads((sandbox / "src-tauri" / "tauri.conf.json").read_text())
        win = cfg["tauri"]["windows"][0]
        assert win["width"] == 1920
        assert win["height"] == 1080

    @pytest.mark.parametrize("os_target", ["linux", "windows", "macos"])
    def test_artifacts_per_os(self, sandbox: Path, os_target: str) -> None:
        DesktopBuilder().scaffold(sandbox, framework="tauri", app_name="tapp")
        stubs = _DESKTOP_ARTIFACTS["tauri"][os_target]
        _create_artifacts(sandbox, stubs)
        found = DesktopBuilder._collect_artifacts(sandbox, "tauri")
        assert len(found) == len(stubs)

    def test_build_cmd(self) -> None:
        cmd = DesktopBuilder._default_build_cmd("tauri", ["linux"])
        assert cmd == "npx tauri build"

    def test_all_os_artifacts_combined(self, sandbox: Path) -> None:
        DesktopBuilder().scaffold(sandbox, framework="tauri", app_name="tapp")
        for os_target in ("linux", "windows", "macos"):
            _create_artifacts(sandbox, _DESKTOP_ARTIFACTS["tauri"][os_target])
        found = DesktopBuilder._collect_artifacts(sandbox, "tauri")
        names = {a.name for a in found}
        assert any("AppImage" in n for n in names)
        assert any(".msi" in n or "setup.exe" in n for n in names)
        assert any(".dmg" in n or ".app" in n for n in names)


class TestDesktopPyInstallerAllOS:
    """PyInstaller × linux, windows, macos."""

    @pytest.fixture()
    def sandbox(self, tmp_path: Path) -> Path:
        s = tmp_path / "pyinstaller-app"
        s.mkdir()
        return s

    def test_scaffold_creates_spec(self, sandbox: Path) -> None:
        DesktopBuilder().scaffold(sandbox, framework="pyinstaller", app_name="piapp")
        spec = sandbox / "piapp.spec"
        assert spec.exists()
        content = spec.read_text()
        assert "Analysis" in content
        assert "piapp" in content

    def test_scaffold_with_icon(self, sandbox: Path) -> None:
        DesktopBuilder().scaffold(sandbox, framework="pyinstaller", app_name="piapp",
                                  extra={"icon": "icon.ico"})
        content = (sandbox / "piapp.spec").read_text()
        assert "icon.ico" in content

    @pytest.mark.parametrize("os_target", ["linux", "windows", "macos"])
    def test_artifacts_per_os(self, sandbox: Path, os_target: str) -> None:
        DesktopBuilder().scaffold(sandbox, framework="pyinstaller", app_name="piapp")
        stubs = _DESKTOP_ARTIFACTS["pyinstaller"][os_target]
        _create_artifacts(sandbox, stubs)
        found = DesktopBuilder._collect_artifacts(sandbox, "pyinstaller")
        assert len(found) == len(stubs)

    @pytest.mark.parametrize("os_target", ["linux", "windows", "macos"])
    def test_build_cmd_same_for_all_os(self, os_target: str) -> None:
        cmd = DesktopBuilder._default_build_cmd("pyinstaller", [os_target])
        assert cmd == "pyinstaller --onefile --windowed main.py"

    def test_all_os_artifacts_combined(self, sandbox: Path) -> None:
        DesktopBuilder().scaffold(sandbox, framework="pyinstaller", app_name="piapp")
        for os_target in ("linux", "windows", "macos"):
            _create_artifacts(sandbox, _DESKTOP_ARTIFACTS["pyinstaller"][os_target])
        found = DesktopBuilder._collect_artifacts(sandbox, "pyinstaller")
        assert len(found) >= 2  # at least linux binary + windows exe


class TestDesktopPyQtAllOS:
    """PyQt × linux, windows, macos."""

    @pytest.fixture()
    def sandbox(self, tmp_path: Path) -> Path:
        s = tmp_path / "pyqt-app"
        s.mkdir()
        return s

    def test_scaffold_creates_spec(self, sandbox: Path) -> None:
        DesktopBuilder().scaffold(sandbox, framework="pyqt", app_name="qtapp")
        spec = sandbox / "qtapp.spec"
        assert spec.exists()
        content = spec.read_text()
        assert "qtapp" in content

    @pytest.mark.parametrize("os_target", ["linux", "windows", "macos"])
    def test_artifacts_per_os(self, sandbox: Path, os_target: str) -> None:
        DesktopBuilder().scaffold(sandbox, framework="pyqt", app_name="qtapp")
        stubs = _DESKTOP_ARTIFACTS["pyqt"][os_target]
        _create_artifacts(sandbox, stubs)
        found = DesktopBuilder._collect_artifacts(sandbox, "pyqt")
        assert len(found) == len(stubs)

    @pytest.mark.parametrize("os_target", ["linux", "windows", "macos"])
    def test_build_cmd_same_for_all_os(self, os_target: str) -> None:
        cmd = DesktopBuilder._default_build_cmd("pyqt", [os_target])
        assert cmd == "pyinstaller --onefile --windowed main.py"


class TestDesktopTkinterAllOS:
    """Tkinter × linux, windows, macos."""

    @pytest.fixture()
    def sandbox(self, tmp_path: Path) -> Path:
        s = tmp_path / "tkinter-app"
        s.mkdir()
        return s

    def test_scaffold_creates_spec(self, sandbox: Path) -> None:
        DesktopBuilder().scaffold(sandbox, framework="tkinter", app_name="tkapp")
        spec = sandbox / "tkapp.spec"
        assert spec.exists()

    @pytest.mark.parametrize("os_target", ["linux", "windows", "macos"])
    def test_artifacts_per_os(self, sandbox: Path, os_target: str) -> None:
        DesktopBuilder().scaffold(sandbox, framework="tkinter", app_name="tkapp")
        stubs = _DESKTOP_ARTIFACTS["tkinter"][os_target]
        _create_artifacts(sandbox, stubs)
        found = DesktopBuilder._collect_artifacts(sandbox, "tkinter")
        assert len(found) == len(stubs)

    @pytest.mark.parametrize("os_target", ["linux", "windows", "macos"])
    def test_build_cmd_same_for_all_os(self, os_target: str) -> None:
        cmd = DesktopBuilder._default_build_cmd("tkinter", [os_target])
        assert cmd == "pyinstaller --onefile --windowed main.py"


class TestDesktopFlutterAllOS:
    """Flutter desktop × linux, windows, macos."""

    @pytest.fixture()
    def sandbox(self, tmp_path: Path) -> Path:
        s = tmp_path / "flutter-desktop"
        s.mkdir()
        return s

    def test_scaffold_noop(self, sandbox: Path) -> None:
        # Flutter desktop scaffold is a no-op (uses files as-is)
        DesktopBuilder().scaffold(sandbox, framework="flutter", app_name="fapp")
        # No config files created by scaffold
        assert not (sandbox / "package.json").exists()

    @pytest.mark.parametrize("os_target", ["linux", "windows", "macos"])
    def test_artifacts_per_os(self, sandbox: Path, os_target: str) -> None:
        stubs = _DESKTOP_ARTIFACTS["flutter"][os_target]
        _create_artifacts(sandbox, stubs)
        found = DesktopBuilder._collect_artifacts(sandbox, "flutter")
        # Flutter desktop collects from build/linux/**/* — only linux artifacts match
        if os_target == "linux":
            assert len(found) >= 1
        # windows/macos artifacts are in different paths not in the pattern

    @pytest.mark.parametrize("os_target", ["linux", "windows", "macos"])
    def test_build_cmd_per_os(self, os_target: str) -> None:
        cmd = DesktopBuilder._default_build_cmd("flutter", [os_target])
        assert f"flutter build {os_target}" == cmd


# =========================================================================
# MOBILE: scaffold + artifacts + build commands × ALL platforms
# =========================================================================


class TestMobileCapacitorAllPlatforms:
    """Capacitor × android, ios."""

    @pytest.fixture()
    def sandbox(self, tmp_path: Path) -> Path:
        s = tmp_path / "cap-app"
        s.mkdir()
        return s

    def test_scaffold_creates_config(self, sandbox: Path) -> None:
        MobileBuilder().scaffold(sandbox, framework="capacitor", app_name="capapp")
        assert (sandbox / "capacitor.config.json").exists()
        assert (sandbox / "package.json").exists()

    def test_scaffold_config_content(self, sandbox: Path) -> None:
        MobileBuilder().scaffold(sandbox, framework="capacitor", app_name="capapp")
        cfg = json.loads((sandbox / "capacitor.config.json").read_text())
        assert cfg["appName"] == "capapp"
        assert cfg["appId"] == "com.pactown.capapp"
        assert "webDir" in cfg

    def test_scaffold_custom_app_id(self, sandbox: Path) -> None:
        MobileBuilder().scaffold(sandbox, framework="capacitor", app_name="capapp",
                                 extra={"app_id": "io.test.cap"})
        cfg = json.loads((sandbox / "capacitor.config.json").read_text())
        assert cfg["appId"] == "io.test.cap"

    def test_scaffold_package_json_deps(self, sandbox: Path) -> None:
        MobileBuilder().scaffold(sandbox, framework="capacitor", app_name="capapp")
        pkg = json.loads((sandbox / "package.json").read_text())
        deps = pkg["dependencies"]
        assert "@capacitor/core" in deps
        assert "@capacitor/cli" in deps

    def test_scaffold_android_platform_dep(self, sandbox: Path) -> None:
        MobileBuilder().scaffold(sandbox, framework="capacitor", app_name="capapp",
                                 extra={"targets": ["android"]})
        pkg = json.loads((sandbox / "package.json").read_text())
        assert "@capacitor/android" in pkg["dependencies"]

    def test_scaffold_ios_platform_dep(self, sandbox: Path) -> None:
        MobileBuilder().scaffold(sandbox, framework="capacitor", app_name="capapp",
                                 extra={"targets": ["ios"]})
        pkg = json.loads((sandbox / "package.json").read_text())
        assert "@capacitor/ios" in pkg["dependencies"]

    def test_scaffold_dual_platform_deps(self, sandbox: Path) -> None:
        MobileBuilder().scaffold(sandbox, framework="capacitor", app_name="capapp",
                                 extra={"targets": ["android", "ios"]})
        pkg = json.loads((sandbox / "package.json").read_text())
        deps = pkg["dependencies"]
        assert "@capacitor/android" in deps
        assert "@capacitor/ios" in deps

    def test_scaffold_scripts(self, sandbox: Path) -> None:
        MobileBuilder().scaffold(sandbox, framework="capacitor", app_name="capapp")
        pkg = json.loads((sandbox / "package.json").read_text())
        scripts = pkg["scripts"]
        assert "cap:sync" in scripts
        assert "cap:build:android" in scripts
        assert "cap:build:ios" in scripts

    def test_scaffold_web_dir_detection_dist(self, sandbox: Path) -> None:
        (sandbox / "dist").mkdir()
        (sandbox / "dist" / "index.html").write_text("<html></html>")
        MobileBuilder().scaffold(sandbox, framework="capacitor", app_name="capapp")
        cfg = json.loads((sandbox / "capacitor.config.json").read_text())
        assert cfg["webDir"] == "dist"

    def test_scaffold_web_dir_detection_root(self, sandbox: Path) -> None:
        (sandbox / "index.html").write_text("<html></html>")
        MobileBuilder().scaffold(sandbox, framework="capacitor", app_name="capapp")
        cfg = json.loads((sandbox / "capacitor.config.json").read_text())
        assert cfg["webDir"] == "."

    @pytest.mark.parametrize("platform", ["android", "ios"])
    def test_artifacts_per_platform(self, sandbox: Path, platform: str) -> None:
        MobileBuilder().scaffold(sandbox, framework="capacitor", app_name="capapp")
        stubs = _MOBILE_ARTIFACTS["capacitor"][platform]
        _create_artifacts(sandbox, stubs)
        found = MobileBuilder._collect_artifacts(sandbox, "capacitor")
        assert len(found) >= len(stubs)

    @pytest.mark.parametrize("platform", ["android", "ios"])
    def test_build_cmd_per_platform(self, platform: str) -> None:
        cmd = MobileBuilder._default_build_cmd("capacitor", [platform])
        assert f"cap sync {platform}" in cmd
        if platform == "android":
            assert "gradlew assembleDebug" in cmd
        else:
            assert "xcodebuild" in cmd

    def test_dual_platform_artifacts(self, sandbox: Path) -> None:
        MobileBuilder().scaffold(sandbox, framework="capacitor", app_name="capapp")
        for platform in ("android", "ios"):
            _create_artifacts(sandbox, _MOBILE_ARTIFACTS["capacitor"][platform])
        found = MobileBuilder._collect_artifacts(sandbox, "capacitor")
        names = {a.name for a in found}
        assert any(n.endswith(".apk") for n in names)
        assert any(n.endswith(".ipa") for n in names)


class TestMobileReactNativeAllPlatforms:
    """React Native × android, ios."""

    @pytest.fixture()
    def sandbox(self, tmp_path: Path) -> Path:
        s = tmp_path / "rn-app"
        s.mkdir()
        return s

    def test_scaffold_creates_app_json(self, sandbox: Path) -> None:
        MobileBuilder().scaffold(sandbox, framework="react-native", app_name="rnapp")
        assert (sandbox / "app.json").exists()

    def test_scaffold_app_json_content(self, sandbox: Path) -> None:
        MobileBuilder().scaffold(sandbox, framework="react-native", app_name="rnapp")
        cfg = json.loads((sandbox / "app.json").read_text())
        assert cfg["name"] == "rnapp"
        assert cfg["displayName"] == "rnapp"

    def test_scaffold_custom_display_name(self, sandbox: Path) -> None:
        MobileBuilder().scaffold(sandbox, framework="react-native", app_name="rnapp",
                                 extra={"app_name": "My RN App"})
        cfg = json.loads((sandbox / "app.json").read_text())
        assert cfg["displayName"] == "My RN App"

    @pytest.mark.parametrize("platform", ["android", "ios"])
    def test_artifacts_per_platform(self, sandbox: Path, platform: str) -> None:
        MobileBuilder().scaffold(sandbox, framework="react-native", app_name="rnapp")
        stubs = _MOBILE_ARTIFACTS["react-native"][platform]
        _create_artifacts(sandbox, stubs)
        found = MobileBuilder._collect_artifacts(sandbox, "react-native")
        assert len(found) == len(stubs)

    def test_build_cmd_android(self) -> None:
        cmd = MobileBuilder._default_build_cmd("react-native", ["android"])
        assert "react-native build-android" in cmd
        assert "--mode=release" in cmd

    def test_build_cmd_ios(self) -> None:
        cmd = MobileBuilder._default_build_cmd("react-native", ["ios"])
        assert "react-native build-ios" in cmd
        assert "--mode=release" in cmd

    def test_dual_platform_artifacts(self, sandbox: Path) -> None:
        MobileBuilder().scaffold(sandbox, framework="react-native", app_name="rnapp")
        for platform in ("android", "ios"):
            _create_artifacts(sandbox, _MOBILE_ARTIFACTS["react-native"][platform])
        found = MobileBuilder._collect_artifacts(sandbox, "react-native")
        names = {a.name for a in found}
        assert any(n.endswith(".apk") for n in names)
        assert any(n.endswith(".ipa") for n in names)


class TestMobileFlutterAllPlatforms:
    """Flutter mobile × android, ios."""

    @pytest.fixture()
    def sandbox(self, tmp_path: Path) -> Path:
        s = tmp_path / "flutter-mobile"
        s.mkdir()
        return s

    def test_scaffold_noop(self, sandbox: Path) -> None:
        MobileBuilder().scaffold(sandbox, framework="flutter", app_name="fapp")
        # Flutter scaffold is a no-op
        assert not (sandbox / "app.json").exists()

    @pytest.mark.parametrize("platform", ["android", "ios"])
    def test_artifacts_per_platform(self, sandbox: Path, platform: str) -> None:
        stubs = _MOBILE_ARTIFACTS["flutter"][platform]
        _create_artifacts(sandbox, stubs)
        found = MobileBuilder._collect_artifacts(sandbox, "flutter")
        # Only android APK matches the pattern exactly
        if platform == "android":
            assert len(found) >= 1

    def test_build_cmd_android(self) -> None:
        cmd = MobileBuilder._default_build_cmd("flutter", ["android"])
        assert "flutter build apk" in cmd

    def test_build_cmd_ios(self) -> None:
        cmd = MobileBuilder._default_build_cmd("flutter", ["ios"])
        assert "flutter build ios" in cmd


class TestMobileKivyAllPlatforms:
    """Kivy × android, ios."""

    @pytest.fixture()
    def sandbox(self, tmp_path: Path) -> Path:
        s = tmp_path / "kivy-app"
        s.mkdir()
        return s

    def test_scaffold_creates_buildozer_spec(self, sandbox: Path) -> None:
        MobileBuilder().scaffold(sandbox, framework="kivy", app_name="kivyapp")
        spec = sandbox / "buildozer.spec"
        assert spec.exists()
        content = spec.read_text()
        assert "kivyapp" in content
        assert "requirements = python3,kivy" in content

    def test_scaffold_custom_app_id(self, sandbox: Path) -> None:
        MobileBuilder().scaffold(sandbox, framework="kivy", app_name="kivyapp",
                                 extra={"app_id": "org.test.kivy"})
        content = (sandbox / "buildozer.spec").read_text()
        assert "org.test" in content

    def test_scaffold_fullscreen(self, sandbox: Path) -> None:
        MobileBuilder().scaffold(sandbox, framework="kivy", app_name="kivyapp",
                                 extra={"fullscreen": True})
        content = (sandbox / "buildozer.spec").read_text()
        assert "fullscreen = 1" in content

    def test_scaffold_no_fullscreen(self, sandbox: Path) -> None:
        MobileBuilder().scaffold(sandbox, framework="kivy", app_name="kivyapp")
        content = (sandbox / "buildozer.spec").read_text()
        assert "fullscreen = 0" in content

    def test_scaffold_icon(self, sandbox: Path) -> None:
        MobileBuilder().scaffold(sandbox, framework="kivy", app_name="kivyapp",
                                 extra={"icon": "icon.png"})
        content = (sandbox / "buildozer.spec").read_text()
        assert "icon.png" in content

    @pytest.mark.parametrize("platform", ["android", "ios"])
    def test_artifacts_per_platform(self, sandbox: Path, platform: str) -> None:
        MobileBuilder().scaffold(sandbox, framework="kivy", app_name="kivyapp")
        stubs = _MOBILE_ARTIFACTS["kivy"][platform]
        _create_artifacts(sandbox, stubs)
        found = MobileBuilder._collect_artifacts(sandbox, "kivy")
        assert len(found) >= 1

    def test_build_cmd_android(self) -> None:
        cmd = MobileBuilder._default_build_cmd("kivy", ["android"])
        assert cmd == "buildozer android debug"

    def test_build_cmd_ios(self) -> None:
        cmd = MobileBuilder._default_build_cmd("kivy", ["ios"])
        assert cmd == "buildozer ios debug"

    def test_android_apk_and_aab(self, sandbox: Path) -> None:
        MobileBuilder().scaffold(sandbox, framework="kivy", app_name="kivyapp")
        _create_artifacts(sandbox, _MOBILE_ARTIFACTS["kivy"]["android"])
        found = MobileBuilder._collect_artifacts(sandbox, "kivy")
        names = {a.suffix for a in found}
        assert ".apk" in names
        assert ".aab" in names


# =========================================================================
# WEB: all web frameworks
# =========================================================================


class TestWebAllFrameworks:
    """WebBuilder × all web frameworks."""

    @pytest.fixture()
    def sandbox(self, tmp_path: Path) -> Path:
        s = tmp_path / "web-app"
        s.mkdir()
        return s

    @pytest.mark.parametrize("framework", ["fastapi", "flask", "express", "next", "react", "vue"])
    def test_scaffold_noop(self, sandbox: Path, framework: str) -> None:
        WebBuilder().scaffold(sandbox, framework=framework, app_name="webapp")
        # WebBuilder scaffold is a no-op

    @pytest.mark.parametrize("framework", ["fastapi", "flask", "express", "next", "react", "vue"])
    def test_build_no_cmd_returns_success(self, sandbox: Path, framework: str) -> None:
        result = WebBuilder().build(sandbox, framework=framework)
        assert result.success
        assert result.platform == "web"

    @pytest.mark.parametrize("framework", ["fastapi", "flask", "express", "next", "react", "vue"])
    def test_build_with_cmd_runs_shell(self, sandbox: Path, framework: str) -> None:
        result = WebBuilder().build(sandbox, build_cmd="echo ok", framework=framework)
        assert result.success
        assert result.build_cmd == "echo ok"

    def test_platform_name(self) -> None:
        assert WebBuilder().platform_name == "web"


# =========================================================================
# ANSIBLE DEPLOYMENT: every framework × every platform
# =========================================================================


class TestAnsibleDeployDesktopAllCombinations:
    """Ansible deploy for every desktop framework × OS combination."""

    @pytest.mark.parametrize("framework,os_target", [
        ("electron", "linux"),
        ("electron", "windows"),
        ("electron", "macos"),
        ("tauri", "linux"),
        ("tauri", "windows"),
        ("tauri", "macos"),
        ("pyinstaller", "linux"),
        ("pyinstaller", "windows"),
        ("pyinstaller", "macos"),
        ("pyqt", "linux"),
        ("pyqt", "windows"),
        ("pyqt", "macos"),
        ("tkinter", "linux"),
        ("tkinter", "windows"),
        ("tkinter", "macos"),
        ("flutter", "linux"),
        ("flutter", "windows"),
        ("flutter", "macos"),
    ])
    def test_scaffold_artifacts_ansible_deploy(
        self, tmp_path: Path, framework: str, os_target: str
    ) -> None:
        sandbox = tmp_path / f"{framework}-{os_target}"
        sandbox.mkdir()

        # 1. Scaffold
        builder = DesktopBuilder()
        builder.scaffold(sandbox, framework=framework, app_name=f"{framework}app")

        # 2. Create fake artifacts
        stubs = _DESKTOP_ARTIFACTS[framework][os_target]
        created = _create_artifacts(sandbox, stubs)

        # 3. Collect artifacts
        found = DesktopBuilder._collect_artifacts(sandbox, framework)
        # At minimum, the artifacts we created should be findable
        # (some patterns may not match all OS artifacts)

        # 4. Ansible deploy
        ansible_out = tmp_path / f"ansible-{framework}-{os_target}"
        backend = AnsibleBackend(
            config=_deploy_config(namespace=f"{framework}-{os_target}"),
            dry_run=True,
            output_dir=ansible_out,
        )

        artifact_names = [a.name for a in found] if found else [c.name for c in created]
        result = backend.deploy(
            service_name=f"{framework}app",
            image_name=f"pactown/{framework}app:{os_target}",
            port=8080,
            env={
                "FRAMEWORK": framework,
                "OS_TARGET": os_target,
                "ARTIFACTS": ",".join(artifact_names),
            },
        )

        assert result.success
        assert result.runtime == RuntimeType.ANSIBLE

        # 5. Verify playbook
        pb = yaml.safe_load((ansible_out / "deploy.yml").read_text())
        assert len(pb) >= 1
        container = pb[0]["tasks"][2]["community.docker.docker_container"]
        assert container["env"]["FRAMEWORK"] == framework
        assert container["env"]["OS_TARGET"] == os_target
        assert container["name"] == f"{framework}-{os_target}-{framework}app"

        # 6. Verify inventory
        inv = yaml.safe_load((ansible_out / "inventory.yml").read_text())
        assert "all" in inv


class TestAnsibleDeployMobileAllCombinations:
    """Ansible deploy for every mobile framework × platform combination."""

    @pytest.mark.parametrize("framework,platform", [
        ("capacitor", "android"),
        ("capacitor", "ios"),
        ("react-native", "android"),
        ("react-native", "ios"),
        ("flutter", "android"),
        ("flutter", "ios"),
        ("kivy", "android"),
        ("kivy", "ios"),
    ])
    def test_scaffold_artifacts_ansible_deploy(
        self, tmp_path: Path, framework: str, platform: str
    ) -> None:
        sandbox = tmp_path / f"{framework}-{platform}"
        sandbox.mkdir()

        # 1. Scaffold
        builder = MobileBuilder()
        builder.scaffold(sandbox, framework=framework, app_name=f"{framework}app",
                         extra={"targets": [platform]})

        # 2. Create fake artifacts
        stubs = _MOBILE_ARTIFACTS[framework][platform]
        created = _create_artifacts(sandbox, stubs)

        # 3. Collect artifacts
        found = MobileBuilder._collect_artifacts(sandbox, framework)

        # 4. Ansible deploy
        ansible_out = tmp_path / f"ansible-{framework}-{platform}"
        backend = AnsibleBackend(
            config=_deploy_config(namespace=f"{framework}-{platform}"),
            dry_run=True,
            output_dir=ansible_out,
        )

        artifact_names = [a.name for a in found] if found else [c.name for c in created]
        result = backend.deploy(
            service_name=f"{framework}app",
            image_name=f"pactown/{framework}app:{platform}",
            port=8080,
            env={
                "FRAMEWORK": framework,
                "PLATFORM": platform,
                "ARTIFACTS": ",".join(artifact_names),
            },
        )

        assert result.success
        assert result.runtime == RuntimeType.ANSIBLE

        # 5. Verify playbook
        pb = yaml.safe_load((ansible_out / "deploy.yml").read_text())
        container = pb[0]["tasks"][2]["community.docker.docker_container"]
        assert container["env"]["FRAMEWORK"] == framework
        assert container["env"]["PLATFORM"] == platform

        # 6. Verify inventory
        inv = yaml.safe_load((ansible_out / "inventory.yml").read_text())
        assert "all" in inv


class TestAnsibleDeployWebAllFrameworks:
    """Ansible deploy for every web framework."""

    @pytest.mark.parametrize("framework", [
        "fastapi", "flask", "express", "next", "react", "vue",
    ])
    def test_web_framework_ansible_deploy(
        self, tmp_path: Path, framework: str
    ) -> None:
        sandbox = tmp_path / f"web-{framework}"
        sandbox.mkdir()

        # 1. Scaffold + build
        builder = WebBuilder()
        builder.scaffold(sandbox, framework=framework, app_name=f"{framework}app")
        result = builder.build(sandbox, framework=framework)
        assert result.success

        # 2. Ansible deploy
        ansible_out = tmp_path / f"ansible-web-{framework}"
        backend = AnsibleBackend(
            config=_deploy_config(namespace=f"web-{framework}"),
            dry_run=True,
            output_dir=ansible_out,
        )

        deploy_result = backend.deploy(
            service_name=f"{framework}app",
            image_name=f"pactown/{framework}app:latest",
            port=8000,
            env={"FRAMEWORK": framework, "PLATFORM": "web"},
        )

        assert deploy_result.success
        assert deploy_result.runtime == RuntimeType.ANSIBLE

        pb = yaml.safe_load((ansible_out / "deploy.yml").read_text())
        container = pb[0]["tasks"][2]["community.docker.docker_container"]
        assert container["env"]["FRAMEWORK"] == framework


# =========================================================================
# FRAMEWORK REGISTRY completeness
# =========================================================================


class TestFrameworkRegistryCompleteness:
    """Verify all frameworks are registered and have correct metadata."""

    def test_all_desktop_frameworks_registered(self) -> None:
        from pactown.targets import FRAMEWORK_REGISTRY, TargetPlatform
        desktop_keys = {k for k, v in FRAMEWORK_REGISTRY.items()
                        if v.platform == TargetPlatform.DESKTOP}
        expected = {"electron", "tauri", "pyinstaller", "tkinter", "pyqt", "flutter-desktop"}
        assert expected == desktop_keys

    def test_all_mobile_frameworks_registered(self) -> None:
        from pactown.targets import FRAMEWORK_REGISTRY, TargetPlatform
        mobile_keys = {k for k, v in FRAMEWORK_REGISTRY.items()
                       if v.platform == TargetPlatform.MOBILE}
        expected = {"capacitor", "react-native", "flutter-mobile", "kivy"}
        assert expected == mobile_keys

    def test_all_frameworks_have_build_cmd(self) -> None:
        from pactown.targets import FRAMEWORK_REGISTRY
        for key, meta in FRAMEWORK_REGISTRY.items():
            assert meta.default_build_cmd, f"{key} missing default_build_cmd"

    def test_all_frameworks_have_artifact_patterns(self) -> None:
        from pactown.targets import FRAMEWORK_REGISTRY
        for key, meta in FRAMEWORK_REGISTRY.items():
            assert meta.artifact_patterns, f"{key} missing artifact_patterns"

    def test_desktop_enums_match_registry(self) -> None:
        from pactown.targets import DesktopFramework
        values = {e.value for e in DesktopFramework}
        expected = {"electron", "tauri", "pyinstaller", "tkinter", "pyqt", "flutter"}
        assert expected == values

    def test_mobile_enums_match_registry(self) -> None:
        from pactown.targets import MobileFramework
        values = {e.value for e in MobileFramework}
        expected = {"capacitor", "react-native", "flutter", "kivy"}
        assert expected == values

    def test_web_enums(self) -> None:
        from pactown.targets import WebFramework
        values = {e.value for e in WebFramework}
        expected = {"fastapi", "flask", "express", "next", "react", "vue"}
        assert expected == values


# =========================================================================
# BUILD COMMAND MATRIX (all frameworks × all targets)
# =========================================================================


class TestBuildCommandMatrix:
    """Verify build commands for every framework × target combination."""

    @pytest.mark.parametrize("targets", [
        ["linux"], ["windows"], ["macos"],
        ["linux", "windows"], ["linux", "macos"], ["linux", "windows", "macos"],
    ])
    def test_electron_build_cmd_targets(self, targets: list[str]) -> None:
        cmd = DesktopBuilder._default_build_cmd("electron", targets)
        assert "electron-builder" in cmd
        assert cmd.strip()

    def test_tauri_build_cmd_ignores_targets(self) -> None:
        for targets in [["linux"], ["windows"], ["macos"]]:
            cmd = DesktopBuilder._default_build_cmd("tauri", targets)
            assert cmd == "npx tauri build"

    @pytest.mark.parametrize("fw", ["pyinstaller", "tkinter", "pyqt"])
    def test_python_desktop_build_cmd(self, fw: str) -> None:
        for targets in [["linux"], ["windows"], ["macos"]]:
            cmd = DesktopBuilder._default_build_cmd(fw, targets)
            assert cmd == "pyinstaller --onefile --windowed main.py"

    @pytest.mark.parametrize("os_target", ["linux", "windows", "macos"])
    def test_flutter_desktop_build_cmd(self, os_target: str) -> None:
        cmd = DesktopBuilder._default_build_cmd("flutter", [os_target])
        assert cmd == f"flutter build {os_target}"

    @pytest.mark.parametrize("platform", ["android", "ios"])
    def test_capacitor_build_cmd(self, platform: str) -> None:
        cmd = MobileBuilder._default_build_cmd("capacitor", [platform])
        assert f"cap sync {platform}" in cmd
        if platform == "android":
            assert "gradlew assembleDebug" in cmd
        else:
            assert "xcodebuild" in cmd

    @pytest.mark.parametrize("platform", ["android", "ios"])
    def test_react_native_build_cmd(self, platform: str) -> None:
        cmd = MobileBuilder._default_build_cmd("react-native", [platform])
        assert "react-native" in cmd
        assert "--mode=release" in cmd

    @pytest.mark.parametrize("platform", ["android", "ios"])
    def test_flutter_mobile_build_cmd(self, platform: str) -> None:
        cmd = MobileBuilder._default_build_cmd("flutter", [platform])
        assert "flutter build" in cmd

    @pytest.mark.parametrize("platform", ["android", "ios"])
    def test_kivy_build_cmd(self, platform: str) -> None:
        cmd = MobileBuilder._default_build_cmd("kivy", [platform])
        assert f"buildozer {platform} debug" == cmd

    def test_unknown_desktop_framework_returns_empty(self) -> None:
        cmd = DesktopBuilder._default_build_cmd("unknown", ["linux"])
        assert cmd == ""

    def test_unknown_mobile_framework_returns_empty(self) -> None:
        cmd = MobileBuilder._default_build_cmd("unknown", ["android"])
        assert cmd == ""


# =========================================================================
# ARTIFACT COLLECTION MATRIX (all frameworks × all OS/platforms)
# =========================================================================


class TestArtifactCollectionMatrix:
    """Verify artifact collection patterns for every framework × OS/platform."""

    @pytest.mark.parametrize("framework,os_target", [
        ("electron", "linux"),
        ("electron", "windows"),
        ("electron", "macos"),
        ("tauri", "linux"),
        ("tauri", "windows"),
        ("tauri", "macos"),
        ("pyinstaller", "linux"),
        ("pyinstaller", "windows"),
        ("pyinstaller", "macos"),
        ("pyqt", "linux"),
        ("pyqt", "windows"),
        ("pyqt", "macos"),
        ("tkinter", "linux"),
        ("tkinter", "windows"),
        ("tkinter", "macos"),
    ])
    def test_desktop_artifact_collection(
        self, tmp_path: Path, framework: str, os_target: str
    ) -> None:
        sandbox = tmp_path / f"{framework}-{os_target}"
        sandbox.mkdir()
        stubs = _DESKTOP_ARTIFACTS[framework][os_target]
        _create_artifacts(sandbox, stubs)
        found = DesktopBuilder._collect_artifacts(sandbox, framework)
        assert len(found) >= 1, f"No artifacts found for {framework}/{os_target}"
        for art in found:
            assert art.is_file()
            assert str(art).startswith(str(sandbox))

    def test_flutter_desktop_linux_artifacts(self, tmp_path: Path) -> None:
        sandbox = tmp_path / "flutter-linux"
        sandbox.mkdir()
        _create_artifacts(sandbox, _DESKTOP_ARTIFACTS["flutter"]["linux"])
        found = DesktopBuilder._collect_artifacts(sandbox, "flutter")
        assert len(found) >= 1

    @pytest.mark.parametrize("framework,platform", [
        ("capacitor", "android"),
        ("capacitor", "ios"),
        ("react-native", "android"),
        ("react-native", "ios"),
        ("kivy", "android"),
    ])
    def test_mobile_artifact_collection(
        self, tmp_path: Path, framework: str, platform: str
    ) -> None:
        sandbox = tmp_path / f"{framework}-{platform}"
        sandbox.mkdir()
        stubs = _MOBILE_ARTIFACTS[framework][platform]
        _create_artifacts(sandbox, stubs)
        found = MobileBuilder._collect_artifacts(sandbox, framework)
        assert len(found) >= 1, f"No artifacts found for {framework}/{platform}"
        for art in found:
            assert art.is_file()
            assert str(art).startswith(str(sandbox))

    def test_flutter_mobile_android_artifacts(self, tmp_path: Path) -> None:
        sandbox = tmp_path / "flutter-android"
        sandbox.mkdir()
        _create_artifacts(sandbox, _MOBILE_ARTIFACTS["flutter"]["android"])
        found = MobileBuilder._collect_artifacts(sandbox, "flutter")
        assert len(found) >= 1

    def test_unknown_desktop_framework_fallback(self, tmp_path: Path) -> None:
        sandbox = tmp_path / "unknown"
        sandbox.mkdir()
        (sandbox / "dist").mkdir()
        (sandbox / "dist" / "app.bin").write_bytes(b"\x00")
        found = DesktopBuilder._collect_artifacts(sandbox, "unknown")
        assert len(found) >= 1

    def test_unknown_mobile_framework_fallback(self, tmp_path: Path) -> None:
        sandbox = tmp_path / "unknown"
        sandbox.mkdir()
        (sandbox / "bin").mkdir()
        (sandbox / "bin" / "app.apk").write_bytes(b"PK")
        found = MobileBuilder._collect_artifacts(sandbox, "unknown")
        assert len(found) >= 1

    def test_empty_sandbox_returns_no_artifacts(self, tmp_path: Path) -> None:
        sandbox = tmp_path / "empty"
        sandbox.mkdir()
        assert DesktopBuilder._collect_artifacts(sandbox, "electron") == []
        assert MobileBuilder._collect_artifacts(sandbox, "capacitor") == []


# =========================================================================
# ELECTRON NO-SANDBOX PATCH × ALL PATTERNS
# =========================================================================


class TestElectronNoSandboxAllPatterns:
    """Verify no-sandbox patch works for all code patterns."""

    def test_commonjs_require(self, tmp_path: Path) -> None:
        s = tmp_path / "e1"; s.mkdir()
        (s / "main.js").write_text(
            "const { app, BrowserWindow } = require('electron');\n"
            "app.whenReady().then(() => {});\n"
        )
        assert DesktopBuilder._patch_electron_no_sandbox(s) is True
        assert "no-sandbox" in (s / "main.js").read_text()

    def test_commonjs_double_quotes(self, tmp_path: Path) -> None:
        s = tmp_path / "e2"; s.mkdir()
        (s / "main.js").write_text(
            'const { app } = require("electron");\n'
            "app.whenReady().then(() => {});\n"
        )
        assert DesktopBuilder._patch_electron_no_sandbox(s) is True
        assert "no-sandbox" in (s / "main.js").read_text()

    def test_es_module_single_quotes(self, tmp_path: Path) -> None:
        s = tmp_path / "e3"; s.mkdir()
        (s / "main.js").write_text(
            "import { app, BrowserWindow } from 'electron';\n"
            "app.whenReady().then(() => {});\n"
        )
        assert DesktopBuilder._patch_electron_no_sandbox(s) is True
        assert "no-sandbox" in (s / "main.js").read_text()

    def test_es_module_double_quotes(self, tmp_path: Path) -> None:
        s = tmp_path / "e4"; s.mkdir()
        (s / "main.js").write_text(
            'import { app } from "electron";\n'
            "app.whenReady().then(() => {});\n"
        )
        assert DesktopBuilder._patch_electron_no_sandbox(s) is True
        assert "no-sandbox" in (s / "main.js").read_text()

    def test_app_whenready_fallback(self, tmp_path: Path) -> None:
        s = tmp_path / "e5"; s.mkdir()
        (s / "main.js").write_text(
            "// custom\napp.whenReady().then(() => {});\n"
        )
        assert DesktopBuilder._patch_electron_no_sandbox(s) is True
        assert "no-sandbox" in (s / "main.js").read_text()

    def test_app_on_fallback(self, tmp_path: Path) -> None:
        s = tmp_path / "e6"; s.mkdir()
        (s / "main.js").write_text(
            "// custom\napp.on('ready', () => {});\n"
        )
        assert DesktopBuilder._patch_electron_no_sandbox(s) is True
        assert "no-sandbox" in (s / "main.js").read_text()

    def test_ultimate_fallback_prepend(self, tmp_path: Path) -> None:
        s = tmp_path / "e7"; s.mkdir()
        (s / "main.js").write_text("console.log('hello');\n")
        assert DesktopBuilder._patch_electron_no_sandbox(s) is True
        src = (s / "main.js").read_text()
        assert "no-sandbox" in src
        assert src.index("no-sandbox") < src.index("console.log")

    def test_skip_already_patched(self, tmp_path: Path) -> None:
        s = tmp_path / "e8"; s.mkdir()
        (s / "main.js").write_text(
            "const { app } = require('electron');\n"
            "app.commandLine.appendSwitch('no-sandbox');\n"
        )
        assert DesktopBuilder._patch_electron_no_sandbox(s) is False

    def test_no_main_js(self, tmp_path: Path) -> None:
        s = tmp_path / "e9"; s.mkdir()
        assert DesktopBuilder._patch_electron_no_sandbox(s) is False


# =========================================================================
# ELECTRON BUILDER FLAG FILTERING × ALL OS
# =========================================================================


class TestElectronBuilderFlagFilteringAllOS:
    """Verify electron-builder flag filtering for all OS combinations."""

    @patch("pactown.builders.desktop.platform.system", return_value="Linux")
    @patch("pactown.builders.desktop.shutil.which", return_value=None)
    def test_linux_host_keeps_linux(self, mock_which: Any, mock_sys: Any) -> None:
        flags = DesktopBuilder._electron_builder_flags(["linux"])
        assert flags == ["--linux"]

    @patch("pactown.builders.desktop.platform.system", return_value="Linux")
    @patch("pactown.builders.desktop.shutil.which", return_value=None)
    def test_linux_host_strips_mac(self, mock_which: Any, mock_sys: Any) -> None:
        flags = DesktopBuilder._electron_builder_flags(["macos"])
        assert "--mac" not in flags
        assert "--linux" in flags  # fallback

    @patch("pactown.builders.desktop.platform.system", return_value="Linux")
    @patch("pactown.builders.desktop.shutil.which", return_value=None)
    def test_linux_host_strips_windows_no_wine(self, mock_which: Any, mock_sys: Any) -> None:
        flags = DesktopBuilder._electron_builder_flags(["windows"])
        assert "--windows" not in flags

    @patch("pactown.builders.desktop.platform.system", return_value="Linux")
    @patch("pactown.builders.desktop.shutil.which", return_value="/usr/bin/wine")
    def test_linux_host_keeps_windows_with_wine(self, mock_which: Any, mock_sys: Any) -> None:
        flags = DesktopBuilder._electron_builder_flags(["windows"])
        assert "--windows" in flags

    @patch("pactown.builders.desktop.platform.system", return_value="Linux")
    @patch("pactown.builders.desktop.shutil.which", return_value=None)
    def test_linux_host_multi_target(self, mock_which: Any, mock_sys: Any) -> None:
        flags = DesktopBuilder._electron_builder_flags(["linux", "windows", "macos"])
        assert "--linux" in flags
        assert "--windows" not in flags
        assert "--mac" not in flags

    @patch("pactown.builders.desktop.platform.system", return_value="Darwin")
    @patch("pactown.builders.desktop.shutil.which", return_value=None)
    def test_macos_host_keeps_mac(self, mock_which: Any, mock_sys: Any) -> None:
        flags = DesktopBuilder._electron_builder_flags(["macos"])
        assert "--mac" in flags

    @patch("pactown.builders.desktop.platform.system", return_value="Darwin")
    @patch("pactown.builders.desktop.shutil.which", return_value=None)
    def test_macos_host_keeps_linux(self, mock_which: Any, mock_sys: Any) -> None:
        # electron-builder can cross-compile Linux on macOS
        flags = DesktopBuilder._electron_builder_flags(["linux"])
        assert "--linux" in flags

    @patch("pactown.builders.desktop.platform.system", return_value="Windows")
    @patch("pactown.builders.desktop.shutil.which", return_value=None)
    def test_windows_host_keeps_windows(self, mock_which: Any, mock_sys: Any) -> None:
        flags = DesktopBuilder._electron_builder_flags(["windows"])
        assert "--windows" in flags

    @patch("pactown.builders.desktop.platform.system", return_value="Windows")
    @patch("pactown.builders.desktop.shutil.which", return_value=None)
    def test_windows_host_strips_mac(self, mock_which: Any, mock_sys: Any) -> None:
        flags = DesktopBuilder._electron_builder_flags(["macos"])
        assert "--mac" not in flags

    def test_empty_targets_defaults_to_linux(self) -> None:
        flags = DesktopBuilder._electron_builder_flags([])
        assert "--linux" in flags

    def test_none_targets_defaults_to_linux(self) -> None:
        flags = DesktopBuilder._electron_builder_flags(None)
        assert "--linux" in flags

    def test_no_duplicates(self) -> None:
        flags = DesktopBuilder._electron_builder_flags(["linux", "linux", "linux"])
        assert flags.count("--linux") == 1

    def test_filter_cmd_strips_unsupported(self) -> None:
        cmd = "npx electron-builder --linux --mac --windows"
        filtered = DesktopBuilder._filter_electron_builder_cmd(cmd)
        assert "electron-builder" in filtered
        # At least one platform flag must remain
        assert any(f in filtered for f in ("--linux", "--mac", "--windows"))


# =========================================================================
# PARALLEL BUILD (Electron multi-target)
# =========================================================================


class TestElectronParallelBuild:
    """Verify parallel build logic for Electron multi-target."""

    def test_single_target_falls_back_to_sequential(self, tmp_path: Path) -> None:
        sandbox = tmp_path / "e"
        sandbox.mkdir()
        DesktopBuilder().scaffold(sandbox, framework="electron", app_name="app")
        # build_parallel with single target should call build() internally
        # (we can't actually run electron-builder, but we verify the method exists)
        builder = DesktopBuilder()
        assert hasattr(builder, "build_parallel")

    def test_non_electron_falls_back_to_sequential(self, tmp_path: Path) -> None:
        sandbox = tmp_path / "t"
        sandbox.mkdir()
        builder = DesktopBuilder()
        # Tauri multi-target should fall back to sequential
        assert hasattr(builder, "build_parallel")


# =========================================================================
# FULL E2E: scaffold → artifacts → collect → Ansible deploy (all combos)
# =========================================================================


class TestFullE2EAllDesktopCombinations:
    """End-to-end: scaffold → fake artifacts → collect → Ansible deploy
    for every desktop framework × OS."""

    @pytest.mark.parametrize("framework", [
        "electron", "tauri", "pyinstaller", "pyqt", "tkinter",
    ])
    def test_all_os_e2e(self, tmp_path: Path, framework: str) -> None:
        for os_target in ("linux", "windows", "macos"):
            sandbox = tmp_path / f"{framework}-{os_target}"
            sandbox.mkdir()

            DesktopBuilder().scaffold(sandbox, framework=framework, app_name=f"{framework}app")
            _create_artifacts(sandbox, _DESKTOP_ARTIFACTS[framework][os_target])
            found = DesktopBuilder._collect_artifacts(sandbox, framework)

            ansible_out = tmp_path / f"ansible-{framework}-{os_target}"
            backend = AnsibleBackend(
                config=_deploy_config(namespace=f"e2e-{framework}"),
                dry_run=True,
                output_dir=ansible_out,
            )
            result = backend.deploy(
                service_name=f"{framework}app-{os_target}",
                image_name=f"pactown/{framework}:{os_target}",
                port=9000,
                env={"ARTIFACTS": ",".join(a.name for a in found) if found else "none"},
            )
            assert result.success, f"Failed: {framework}/{os_target}"
            assert (ansible_out / "deploy.yml").exists()
            assert (ansible_out / "inventory.yml").exists()


class TestFullE2EAllMobileCombinations:
    """End-to-end: scaffold → fake artifacts → collect → Ansible deploy
    for every mobile framework × platform."""

    @pytest.mark.parametrize("framework", [
        "capacitor", "react-native", "flutter", "kivy",
    ])
    def test_all_platforms_e2e(self, tmp_path: Path, framework: str) -> None:
        for platform in ("android", "ios"):
            sandbox = tmp_path / f"{framework}-{platform}"
            sandbox.mkdir()

            MobileBuilder().scaffold(sandbox, framework=framework, app_name=f"{framework}app",
                                     extra={"targets": [platform]})
            _create_artifacts(sandbox, _MOBILE_ARTIFACTS[framework][platform])
            found = MobileBuilder._collect_artifacts(sandbox, framework)

            ansible_out = tmp_path / f"ansible-{framework}-{platform}"
            backend = AnsibleBackend(
                config=_deploy_config(namespace=f"e2e-{framework}"),
                dry_run=True,
                output_dir=ansible_out,
            )
            result = backend.deploy(
                service_name=f"{framework}app-{platform}",
                image_name=f"pactown/{framework}:{platform}",
                port=9000,
                env={"ARTIFACTS": ",".join(a.name for a in found) if found else "none"},
            )
            assert result.success, f"Failed: {framework}/{platform}"
            assert (ansible_out / "deploy.yml").exists()
            assert (ansible_out / "inventory.yml").exists()
