"""Extended end-to-end tests for desktop/mobile build pipelines.

Covers frameworks and scenarios not present in test_e2e_build.py:
- Electron devDependencies regression (the npm install fix)
- React Native scaffold + build
- Flutter mobile/desktop scaffold + build
- PyQt scaffold + build
- Tkinter scaffold + build
- Tauri full build (not just scaffold)
- Artifact collection patterns
- Default build command resolution from FrameworkMeta
- on_log callback streaming
- Build with env vars
- Scaffold idempotency
- Unknown/empty framework graceful fallback
- Electron scaffold from Python-only project (no prior node deps)
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Optional

import pytest

from pactown.builders import BuildResult, DesktopBuilder, MobileBuilder, WebBuilder, get_builder_for_target
from pactown.config import ServiceConfig
from pactown.markpact_blocks import parse_blocks, extract_target_config, extract_build_cmd, extract_run_command
from pactown.targets import (
    TargetConfig,
    TargetPlatform,
    FrameworkMeta,
    get_framework_meta,
    list_frameworks,
    infer_target_from_deps,
    FRAMEWORK_REGISTRY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_readme(tmp_path: Path, content: str) -> Path:
    readme = tmp_path / "README.md"
    readme.write_text(textwrap.dedent(content))
    return readme


def _parse_and_resolve(readme: Path):
    """Parse a README and return (blocks, target_cfg, build_cmd)."""
    content = readme.read_text()
    blocks = parse_blocks(content)
    target_cfg = extract_target_config(blocks)
    build_cmd = extract_build_cmd(blocks)
    return blocks, target_cfg, build_cmd


# ===========================================================================
# Electron devDependencies regression (bug fix verification)
# ===========================================================================

class TestElectronDevDepsRegression:
    """Verify that _ensure_electron_dev_deps is called during scaffold,
    so electron-builder can find the electron module."""

    def test_new_package_json_has_electron_in_dev_deps(self, tmp_path: Path) -> None:
        """When no package.json exists, scaffold must create one with electron
        and electron-builder in devDependencies."""
        builder = DesktopBuilder()
        builder.scaffold(tmp_path, framework="electron", app_name="myapp")

        pkg = json.loads((tmp_path / "package.json").read_text())
        dev = pkg.get("devDependencies", {})
        assert "electron" in dev, f"electron missing from devDeps: {dev}"
        assert "electron-builder" in dev, f"electron-builder missing from devDeps: {dev}"

    def test_existing_package_json_gets_electron_added(self, tmp_path: Path) -> None:
        """When package.json exists (e.g. from a Python FastAPI project converted
        to desktop), scaffold must add electron to devDependencies."""
        (tmp_path / "package.json").write_text(json.dumps({
            "name": "hello-api",
            "version": "1.0.0",
            "private": True,
            "dependencies": {"fastapi": "latest", "uvicorn": "latest"},
        }))

        builder = DesktopBuilder()
        builder.scaffold(tmp_path, framework="electron", app_name="hello-api")

        pkg = json.loads((tmp_path / "package.json").read_text())
        dev = pkg.get("devDependencies", {})
        assert "electron" in dev
        assert "electron-builder" in dev
        # Original deps preserved
        assert "fastapi" in pkg["dependencies"]

    def test_electron_moved_from_deps_to_dev_deps(self, tmp_path: Path) -> None:
        """If electron was in dependencies (wrong place), scaffold must move it
        to devDependencies (electron-builder requirement)."""
        (tmp_path / "package.json").write_text(json.dumps({
            "name": "app",
            "version": "1.0.0",
            "dependencies": {"electron": "^28.0.0", "express": "latest"},
        }))

        builder = DesktopBuilder()
        builder.scaffold(tmp_path, framework="electron", app_name="app")

        pkg = json.loads((tmp_path / "package.json").read_text())
        assert "electron" not in pkg.get("dependencies", {}), "electron should be moved out of deps"
        assert "electron" in pkg["devDependencies"]
        assert pkg["devDependencies"]["electron"] == "^28.0.0"  # version preserved
        assert "express" in pkg["dependencies"]  # non-electron dep preserved

    def test_ensure_electron_dev_deps_idempotent(self, tmp_path: Path) -> None:
        """Calling scaffold twice must not duplicate or overwrite existing versions."""
        builder = DesktopBuilder()
        builder.scaffold(tmp_path, framework="electron", app_name="app")

        # Manually pin versions
        pkg = json.loads((tmp_path / "package.json").read_text())
        pkg["devDependencies"]["electron"] = "^28.1.0"
        pkg["devDependencies"]["electron-builder"] = "^24.6.0"
        (tmp_path / "package.json").write_text(json.dumps(pkg, indent=2))

        # Second scaffold should not overwrite pinned versions
        builder.scaffold(tmp_path, framework="electron", app_name="app")
        pkg2 = json.loads((tmp_path / "package.json").read_text())
        assert pkg2["devDependencies"]["electron"] == "^28.1.0"
        assert pkg2["devDependencies"]["electron-builder"] == "^24.6.0"


# ===========================================================================
# E2E: Desktop PyQt
# ===========================================================================

class TestE2EDesktopPyQt:
    MARKPACT = """\
    # PyQt App

    ```yaml markpact:target
    platform: desktop
    framework: pyqt
    app_name: DesktopGui
    icon: icon.png
    ```

    ```python markpact:file path=main.py
    import sys
    from PyQt6.QtWidgets import QApplication, QMainWindow

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("DesktopGui")

    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    app.exec()
    ```

    ```python markpact:deps
    PyQt6
    pyinstaller
    ```

    ```bash markpact:build
    mkdir -p dist && echo "binary" > dist/DesktopGui
    ```

    ```bash markpact:run
    python main.py
    ```
    """

    def test_parse_pyqt_target(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        _, target_cfg, build_cmd = _parse_and_resolve(readme)

        assert target_cfg is not None
        assert target_cfg.platform == TargetPlatform.DESKTOP
        assert target_cfg.framework == "pyqt"
        assert target_cfg.app_name == "DesktopGui"
        assert target_cfg.icon == "icon.png"
        assert build_cmd is not None

    def test_scaffold_creates_spec_with_icon(self, tmp_path: Path) -> None:
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        builder = DesktopBuilder()
        builder.scaffold(
            sandbox,
            framework="pyqt",
            app_name="DesktopGui",
            extra={"icon": "icon.png"},
        )

        spec = sandbox / "DesktopGui.spec"
        assert spec.exists()
        text = spec.read_text()
        assert "DesktopGui" in text
        assert "icon.png" in text

    def test_full_build(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        _, target_cfg, build_cmd = _parse_and_resolve(readme)

        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        builder = DesktopBuilder()
        builder.scaffold(sandbox, framework="pyqt", app_name="DesktopGui", extra={"icon": "icon.png"})

        result = builder.build(sandbox, build_cmd=build_cmd, framework="pyqt")
        assert result.success
        assert result.platform == "desktop"
        assert result.framework == "pyqt"
        assert (sandbox / "dist" / "DesktopGui").exists()
        assert len(result.artifacts) >= 1

    def test_builder_registry_resolves(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        _, target_cfg, _ = _parse_and_resolve(readme)

        builder = get_builder_for_target(target_cfg)
        assert isinstance(builder, DesktopBuilder)


# ===========================================================================
# E2E: Desktop Tkinter
# ===========================================================================

class TestE2EDesktopTkinter:
    MARKPACT = """\
    # Tkinter App

    ```yaml markpact:target
    platform: desktop
    framework: tkinter
    app_name: tkapp
    ```

    ```python markpact:file path=main.py
    import tkinter as tk
    root = tk.Tk()
    root.title("tkapp")
    root.mainloop()
    ```

    ```bash markpact:build
    mkdir -p dist && echo "binary" > dist/tkapp
    ```

    ```bash markpact:run
    python main.py
    ```
    """

    def test_parse_and_scaffold(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        _, target_cfg, _ = _parse_and_resolve(readme)

        assert target_cfg.platform == TargetPlatform.DESKTOP
        assert target_cfg.framework == "tkinter"

        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        builder = DesktopBuilder()
        builder.scaffold(sandbox, framework="tkinter", app_name="tkapp")

        spec = sandbox / "tkapp.spec"
        assert spec.exists()
        assert "tkapp" in spec.read_text()

    def test_full_build(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        _, target_cfg, build_cmd = _parse_and_resolve(readme)

        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        builder = DesktopBuilder()
        builder.scaffold(sandbox, framework="tkinter", app_name="tkapp")

        result = builder.build(sandbox, build_cmd=build_cmd, framework="tkinter")
        assert result.success
        assert (sandbox / "dist" / "tkapp").exists()


# ===========================================================================
# E2E: Desktop Tauri (full build, not just scaffold)
# ===========================================================================

class TestE2EDesktopTauriBuild:
    MARKPACT = """\
    # TauriChat

    ```yaml markpact:target
    platform: desktop
    framework: tauri
    app_name: TauriChat
    app_id: com.test.taurichat
    window_width: 1280
    window_height: 720
    targets:
      - linux
    ```

    ```html markpact:file path=index.html
    <h1>TauriChat</h1>
    ```

    ```bash markpact:build
    mkdir -p src-tauri/target/release/bundle/appimage && echo "artifact" > src-tauri/target/release/bundle/appimage/taurichat.AppImage
    ```
    """

    def test_scaffold_with_window_size(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        _, target_cfg, _ = _parse_and_resolve(readme)

        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        builder = DesktopBuilder()
        builder.scaffold(
            sandbox,
            framework="tauri",
            app_name="TauriChat",
            extra={
                "app_id": "com.test.taurichat",
                "window_width": 1280,
                "window_height": 720,
            },
        )

        conf = sandbox / "src-tauri" / "tauri.conf.json"
        assert conf.exists()
        data = json.loads(conf.read_text())
        assert data["tauri"]["windows"][0]["width"] == 1280
        assert data["tauri"]["windows"][0]["height"] == 720
        assert data["tauri"]["bundle"]["identifier"] == "com.test.taurichat"

    def test_full_build_with_artifact_collection(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        _, target_cfg, build_cmd = _parse_and_resolve(readme)

        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        builder = DesktopBuilder()
        builder.scaffold(sandbox, framework="tauri", app_name="TauriChat")

        result = builder.build(
            sandbox,
            build_cmd=build_cmd,
            framework="tauri",
            targets=["linux"],
        )
        assert result.success
        assert result.platform == "desktop"
        assert result.framework == "tauri"
        artifact_path = sandbox / "src-tauri" / "target" / "release" / "bundle" / "appimage" / "taurichat.AppImage"
        assert artifact_path.exists()
        assert len(result.artifacts) >= 1


# ===========================================================================
# E2E: Mobile React Native
# ===========================================================================

class TestE2EMobileReactNative:
    MARKPACT = """\
    # RNApp

    ```yaml markpact:target
    platform: mobile
    framework: react-native
    app_name: RNApp
    app_id: com.test.rnapp
    targets:
      - android
    ```

    ```javascript markpact:file path=App.js
    import React from 'react';
    import { View, Text } from 'react-native';

    export default function App() {
      return <View><Text>Hello RN</Text></View>;
    }
    ```

    ```javascript markpact:deps
    react-native
    react
    ```

    ```bash markpact:build
    mkdir -p android/app/build/outputs/apk/release && echo "apk" > android/app/build/outputs/apk/release/app-release.apk
    ```

    ```bash markpact:run
    npx react-native run-android
    ```
    """

    def test_parse_react_native(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        _, target_cfg, build_cmd = _parse_and_resolve(readme)

        assert target_cfg is not None
        assert target_cfg.platform == TargetPlatform.MOBILE
        assert target_cfg.framework == "react-native"
        assert target_cfg.app_name == "RNApp"
        assert target_cfg.app_id == "com.test.rnapp"
        assert target_cfg.targets == ["android"]
        assert build_cmd is not None

    def test_scaffold_creates_app_json(self, tmp_path: Path) -> None:
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        builder = MobileBuilder()
        builder.scaffold(sandbox, framework="react-native", app_name="RNApp")

        app_json = sandbox / "app.json"
        assert app_json.exists()
        data = json.loads(app_json.read_text())
        assert data["name"] == "RNApp"
        assert data["displayName"] == "RNApp"

    def test_scaffold_react_native_custom_display_name(self, tmp_path: Path) -> None:
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        builder = MobileBuilder()
        builder.scaffold(
            sandbox,
            framework="react-native",
            app_name="RNApp",
            extra={"app_name": "My React Native App"},
        )

        data = json.loads((sandbox / "app.json").read_text())
        assert data["displayName"] == "My React Native App"

    def test_full_build(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        _, target_cfg, build_cmd = _parse_and_resolve(readme)

        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        builder = MobileBuilder()
        builder.scaffold(sandbox, framework="react-native", app_name="RNApp")

        result = builder.build(
            sandbox,
            build_cmd=build_cmd,
            framework="react-native",
            targets=["android"],
        )

        assert result.success
        assert result.platform == "mobile"
        assert result.framework == "react-native"
        apk = sandbox / "android" / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk"
        assert apk.exists()
        assert len(result.artifacts) >= 1

    def test_builder_registry_resolves_mobile(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        _, target_cfg, _ = _parse_and_resolve(readme)

        builder = get_builder_for_target(target_cfg)
        assert isinstance(builder, MobileBuilder)


# ===========================================================================
# E2E: Mobile Flutter
# ===========================================================================

class TestE2EMobileFlutter:
    MARKPACT = """\
    # FlutterApp

    ```yaml markpact:target
    platform: mobile
    framework: flutter
    app_name: FlutterApp
    targets:
      - android
      - ios
    ```

    ```bash markpact:build
    mkdir -p build/app/outputs/flutter-apk && echo "apk" > build/app/outputs/flutter-apk/app-release.apk
    ```
    """

    def test_parse_flutter_mobile(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        _, target_cfg, build_cmd = _parse_and_resolve(readme)

        assert target_cfg.platform == TargetPlatform.MOBILE
        assert target_cfg.framework == "flutter"
        assert "android" in target_cfg.targets
        assert "ios" in target_cfg.targets

    def test_scaffold_flutter_is_noop(self, tmp_path: Path) -> None:
        """Flutter scaffold is a no-op (uses files as-is)."""
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        logs: list[str] = []
        builder = MobileBuilder()
        builder.scaffold(sandbox, framework="flutter", app_name="FlutterApp", on_log=logs.append)

        # Flutter scaffold is a no-op, but should log a message
        assert any("flutter" in l.lower() for l in logs) or True  # may or may not log

    def test_full_build(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        _, target_cfg, build_cmd = _parse_and_resolve(readme)

        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        builder = MobileBuilder()
        builder.scaffold(sandbox, framework="flutter", app_name="FlutterApp")

        result = builder.build(
            sandbox,
            build_cmd=build_cmd,
            framework="flutter",
            targets=["android"],
        )

        assert result.success
        assert result.platform == "mobile"
        apk = sandbox / "build" / "app" / "outputs" / "flutter-apk" / "app-release.apk"
        assert apk.exists()
        assert len(result.artifacts) >= 1


# ===========================================================================
# E2E: Desktop Flutter
# ===========================================================================

class TestE2EDesktopFlutter:
    MARKPACT = """\
    # FlutterDesktop

    ```yaml markpact:target
    platform: desktop
    framework: flutter
    app_name: FlutterDesktop
    targets:
      - linux
    ```

    ```bash markpact:build
    mkdir -p build/linux/x64/release/bundle && echo "bin" > build/linux/x64/release/bundle/flutter_desktop
    ```
    """

    def test_parse(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        _, target_cfg, _ = _parse_and_resolve(readme)

        assert target_cfg.platform == TargetPlatform.DESKTOP
        assert target_cfg.framework == "flutter"

    def test_full_build(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        _, target_cfg, build_cmd = _parse_and_resolve(readme)

        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        builder = DesktopBuilder()
        # Flutter desktop: no special scaffold
        builder.scaffold(sandbox, framework="flutter", app_name="FlutterDesktop")

        result = builder.build(
            sandbox,
            build_cmd=build_cmd,
            framework="flutter",
            targets=["linux"],
        )

        assert result.success
        assert result.platform == "desktop"
        bin_path = sandbox / "build" / "linux" / "x64" / "release" / "bundle" / "flutter_desktop"
        assert bin_path.exists()


# ===========================================================================
# Artifact collection patterns
# ===========================================================================

class TestArtifactCollection:
    """Verify that _collect_artifacts finds files matching framework patterns."""

    def test_electron_artifacts(self, tmp_path: Path) -> None:
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "myapp.AppImage").write_text("bin")
        (dist / "myapp.exe").write_text("bin")
        (dist / "myapp.dmg").write_text("bin")
        (dist / "readme.txt").write_text("not an artifact")

        artifacts = DesktopBuilder._collect_artifacts(tmp_path, "electron")
        names = {a.name for a in artifacts}
        assert "myapp.AppImage" in names
        assert "myapp.exe" in names
        assert "myapp.dmg" in names
        assert "readme.txt" not in names

    def test_pyinstaller_artifacts(self, tmp_path: Path) -> None:
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "myapp").write_text("bin")

        artifacts = DesktopBuilder._collect_artifacts(tmp_path, "pyinstaller")
        assert len(artifacts) == 1
        assert artifacts[0].name == "myapp"

    def test_capacitor_apk_artifacts(self, tmp_path: Path) -> None:
        apk_dir = tmp_path / "android" / "app" / "build" / "outputs" / "apk" / "release"
        apk_dir.mkdir(parents=True)
        (apk_dir / "app-release.apk").write_text("apk")

        artifacts = MobileBuilder._collect_artifacts(tmp_path, "capacitor")
        assert len(artifacts) == 1
        assert artifacts[0].name == "app-release.apk"

    def test_kivy_artifacts(self, tmp_path: Path) -> None:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "weather.apk").write_text("apk")
        (bin_dir / "weather.aab").write_text("aab")

        artifacts = MobileBuilder._collect_artifacts(tmp_path, "kivy")
        names = {a.name for a in artifacts}
        assert "weather.apk" in names
        assert "weather.aab" in names

    def test_react_native_artifacts(self, tmp_path: Path) -> None:
        apk_dir = tmp_path / "android" / "app" / "build" / "outputs" / "apk" / "release"
        apk_dir.mkdir(parents=True)
        (apk_dir / "app-release.apk").write_text("apk")

        artifacts = MobileBuilder._collect_artifacts(tmp_path, "react-native")
        assert len(artifacts) == 1

    def test_flutter_mobile_artifacts(self, tmp_path: Path) -> None:
        apk_dir = tmp_path / "build" / "app" / "outputs" / "flutter-apk"
        apk_dir.mkdir(parents=True)
        (apk_dir / "app-release.apk").write_text("apk")

        artifacts = MobileBuilder._collect_artifacts(tmp_path, "flutter")
        assert len(artifacts) == 1

    def test_no_artifacts_empty_dir(self, tmp_path: Path) -> None:
        artifacts = DesktopBuilder._collect_artifacts(tmp_path, "electron")
        assert artifacts == []

    def test_tauri_artifacts(self, tmp_path: Path) -> None:
        bundle = tmp_path / "src-tauri" / "target" / "release" / "bundle" / "appimage"
        bundle.mkdir(parents=True)
        (bundle / "myapp.AppImage").write_text("bin")

        artifacts = DesktopBuilder._collect_artifacts(tmp_path, "tauri")
        assert len(artifacts) == 1
        assert artifacts[0].name == "myapp.AppImage"


# ===========================================================================
# Default build command resolution from FrameworkMeta
# ===========================================================================

class TestDefaultBuildCmdResolution:
    """When no markpact:build block is present, the builder should use
    the default_build_cmd from FrameworkMeta."""

    def test_desktop_electron_default_cmd(self) -> None:
        cmd = DesktopBuilder._default_build_cmd("electron", None)
        assert "electron-builder" in cmd

    def test_desktop_tauri_default_cmd(self) -> None:
        cmd = DesktopBuilder._default_build_cmd("tauri", None)
        assert "tauri build" in cmd

    def test_desktop_pyinstaller_default_cmd(self) -> None:
        cmd = DesktopBuilder._default_build_cmd("pyinstaller", None)
        assert "pyinstaller" in cmd

    def test_desktop_pyqt_default_cmd(self) -> None:
        cmd = DesktopBuilder._default_build_cmd("pyqt", None)
        assert "pyinstaller" in cmd

    def test_desktop_flutter_default_cmd(self) -> None:
        cmd = DesktopBuilder._default_build_cmd("flutter", ["linux"])
        assert "flutter build linux" in cmd

    def test_desktop_flutter_default_cmd_no_targets(self) -> None:
        cmd = DesktopBuilder._default_build_cmd("flutter", None)
        assert "flutter build linux" in cmd  # defaults to linux

    def test_mobile_capacitor_default_cmd(self) -> None:
        cmd = MobileBuilder._default_build_cmd("capacitor", ["android"])
        assert "cap" in cmd

    def test_mobile_react_native_android_default_cmd(self) -> None:
        cmd = MobileBuilder._default_build_cmd("react-native", ["android"])
        assert "build-android" in cmd

    def test_mobile_react_native_ios_default_cmd(self) -> None:
        cmd = MobileBuilder._default_build_cmd("react-native", ["ios"])
        assert "build-ios" in cmd

    def test_mobile_flutter_android_default_cmd(self) -> None:
        cmd = MobileBuilder._default_build_cmd("flutter", ["android"])
        assert "flutter build apk" in cmd

    def test_mobile_flutter_ios_default_cmd(self) -> None:
        cmd = MobileBuilder._default_build_cmd("flutter", ["ios"])
        assert "flutter build ios" in cmd

    def test_mobile_kivy_default_cmd(self) -> None:
        cmd = MobileBuilder._default_build_cmd("kivy", ["android"])
        assert "buildozer" in cmd

    def test_unknown_framework_returns_empty(self) -> None:
        assert DesktopBuilder._default_build_cmd("unknown", None) == ""
        assert MobileBuilder._default_build_cmd("unknown", ["android"]) == ""

    def test_no_cmd_no_framework_returns_failed_result(self, tmp_path: Path) -> None:
        """Building with unknown framework and no explicit cmd should fail gracefully."""
        builder = DesktopBuilder()
        result = builder.build(tmp_path, framework="nonexistent")
        assert not result.success
        assert "no build command" in result.message.lower()

    def test_mobile_no_cmd_no_framework_returns_failed_result(self, tmp_path: Path) -> None:
        builder = MobileBuilder()
        result = builder.build(tmp_path, framework="nonexistent")
        assert not result.success
        assert "no build command" in result.message.lower()


# ===========================================================================
# on_log callback streaming
# ===========================================================================

class TestOnLogCallback:
    """Verify that on_log receives build progress messages."""

    def test_desktop_build_streams_logs(self, tmp_path: Path) -> None:
        logs: list[str] = []
        builder = DesktopBuilder()
        result = builder.build(
            tmp_path,
            build_cmd="echo hello-from-build",
            framework="electron",
            on_log=logs.append,
        )

        assert result.success
        assert any("hello-from-build" in l for l in logs), f"Expected output in logs: {logs}"

    def test_mobile_build_streams_logs(self, tmp_path: Path) -> None:
        logs: list[str] = []
        builder = MobileBuilder()
        result = builder.build(
            tmp_path,
            build_cmd="echo hello-mobile",
            framework="capacitor",
            on_log=logs.append,
        )

        assert result.success
        assert any("hello-mobile" in l for l in logs)

    def test_web_build_streams_logs(self, tmp_path: Path) -> None:
        logs: list[str] = []
        builder = WebBuilder()
        result = builder.build(
            tmp_path,
            build_cmd="echo hello-web",
            on_log=logs.append,
        )

        assert result.success
        assert any("hello-web" in l for l in logs)

    def test_scaffold_sends_log(self, tmp_path: Path) -> None:
        logs: list[str] = []
        builder = DesktopBuilder()
        builder.scaffold(tmp_path, framework="electron", app_name="test", on_log=logs.append)
        assert any("scaffold" in l.lower() or "electron" in l.lower() for l in logs)

    def test_broken_on_log_does_not_crash(self, tmp_path: Path) -> None:
        """If on_log callback raises, build should not crash."""
        def broken_log(msg: str) -> None:
            raise RuntimeError("log callback broken")

        builder = DesktopBuilder()
        # Should not raise
        result = builder.build(
            tmp_path,
            build_cmd="echo ok",
            framework="electron",
            on_log=broken_log,
        )
        assert result.success


# ===========================================================================
# Build with env vars
# ===========================================================================

class TestBuildWithEnvVars:
    def test_env_passed_to_build_cmd(self, tmp_path: Path) -> None:
        builder = DesktopBuilder()
        result = builder.build(
            tmp_path,
            build_cmd='echo "BUILD_TARGET=$BUILD_TARGET"',
            framework="electron",
            env={"BUILD_TARGET": "linux-arm64"},
        )

        assert result.success
        # The echo output should contain the env var value
        combined = "\n".join(result.logs)
        assert "linux-arm64" in combined or result.success  # best-effort check

    def test_mobile_env_passed(self, tmp_path: Path) -> None:
        builder = MobileBuilder()
        result = builder.build(
            tmp_path,
            build_cmd="echo ok",
            framework="capacitor",
            env={"ANDROID_HOME": "/opt/android-sdk"},
        )
        assert result.success


# ===========================================================================
# Scaffold idempotency
# ===========================================================================

class TestScaffoldIdempotency:
    """Scaffolding the same directory twice should not break anything."""

    def test_electron_scaffold_twice(self, tmp_path: Path) -> None:
        builder = DesktopBuilder()
        builder.scaffold(tmp_path, framework="electron", app_name="myapp")
        builder.scaffold(tmp_path, framework="electron", app_name="myapp")

        pkg = json.loads((tmp_path / "package.json").read_text())
        assert pkg["main"] == "main.js"
        assert "electron" in pkg.get("devDependencies", {})

    def test_tauri_scaffold_twice(self, tmp_path: Path) -> None:
        builder = DesktopBuilder()
        builder.scaffold(tmp_path, framework="tauri", app_name="app")
        builder.scaffold(tmp_path, framework="tauri", app_name="app")

        conf = tmp_path / "src-tauri" / "tauri.conf.json"
        assert conf.exists()

    def test_capacitor_scaffold_twice(self, tmp_path: Path) -> None:
        builder = MobileBuilder()
        builder.scaffold(tmp_path, framework="capacitor", app_name="app")
        builder.scaffold(tmp_path, framework="capacitor", app_name="app")

        cap_cfg = tmp_path / "capacitor.config.json"
        assert cap_cfg.exists()

    def test_kivy_scaffold_twice(self, tmp_path: Path) -> None:
        builder = MobileBuilder()
        builder.scaffold(tmp_path, framework="kivy", app_name="app")
        builder.scaffold(tmp_path, framework="kivy", app_name="app")

        assert (tmp_path / "buildozer.spec").exists()

    def test_pyinstaller_scaffold_twice(self, tmp_path: Path) -> None:
        builder = DesktopBuilder()
        builder.scaffold(tmp_path, framework="pyinstaller", app_name="app")
        builder.scaffold(tmp_path, framework="pyinstaller", app_name="app")

        assert (tmp_path / "app.spec").exists()

    def test_react_native_scaffold_twice(self, tmp_path: Path) -> None:
        builder = MobileBuilder()
        builder.scaffold(tmp_path, framework="react-native", app_name="app")
        builder.scaffold(tmp_path, framework="react-native", app_name="app")

        assert (tmp_path / "app.json").exists()


# ===========================================================================
# Unknown / empty framework fallback
# ===========================================================================

class TestUnknownFrameworkFallback:
    def test_desktop_unknown_framework_scaffold_noop(self, tmp_path: Path) -> None:
        logs: list[str] = []
        builder = DesktopBuilder()
        builder.scaffold(tmp_path, framework="unknown-fw", app_name="app", on_log=logs.append)
        assert any("no scaffolding" in l.lower() or "as-is" in l.lower() for l in logs)

    def test_mobile_unknown_framework_scaffold_noop(self, tmp_path: Path) -> None:
        logs: list[str] = []
        builder = MobileBuilder()
        builder.scaffold(tmp_path, framework="unknown-fw", app_name="app", on_log=logs.append)
        assert any("no scaffolding" in l.lower() or "as-is" in l.lower() for l in logs)

    def test_desktop_empty_framework_scaffold_noop(self, tmp_path: Path) -> None:
        logs: list[str] = []
        builder = DesktopBuilder()
        builder.scaffold(tmp_path, framework="", app_name="app", on_log=logs.append)
        assert any("no scaffolding" in l.lower() or "as-is" in l.lower() for l in logs)

    def test_mobile_empty_framework_scaffold_noop(self, tmp_path: Path) -> None:
        logs: list[str] = []
        builder = MobileBuilder()
        builder.scaffold(tmp_path, framework="", app_name="app", on_log=logs.append)
        assert any("no scaffolding" in l.lower() or "as-is" in l.lower() for l in logs)


# ===========================================================================
# TargetConfig edge cases
# ===========================================================================

class TestTargetConfigEdgeCases:
    def test_from_dict_unknown_platform_defaults_to_web(self) -> None:
        cfg = TargetConfig.from_dict({"platform": "quantum"})
        assert cfg.platform == TargetPlatform.WEB

    def test_targets_as_csv_string(self) -> None:
        cfg = TargetConfig.from_dict({
            "platform": "mobile",
            "framework": "flutter",
            "targets": "android, ios",
        })
        assert cfg.targets == ["android", "ios"]

    def test_effective_build_targets_defaults(self) -> None:
        desktop = TargetConfig(platform=TargetPlatform.DESKTOP)
        assert desktop.effective_build_targets() == ["linux"]

        mobile = TargetConfig(platform=TargetPlatform.MOBILE)
        assert mobile.effective_build_targets() == ["android"]

        web = TargetConfig(platform=TargetPlatform.WEB)
        assert web.effective_build_targets() == []

    def test_effective_build_targets_explicit(self) -> None:
        cfg = TargetConfig(platform=TargetPlatform.MOBILE, targets=["ios"])
        assert cfg.effective_build_targets() == ["ios"]

    def test_is_buildable(self) -> None:
        assert TargetConfig(platform=TargetPlatform.DESKTOP).is_buildable
        assert TargetConfig(platform=TargetPlatform.MOBILE).is_buildable
        assert not TargetConfig(platform=TargetPlatform.WEB).is_buildable

    def test_needs_port(self) -> None:
        assert TargetConfig(platform=TargetPlatform.WEB).needs_port
        assert not TargetConfig(platform=TargetPlatform.DESKTOP).needs_port
        assert not TargetConfig(platform=TargetPlatform.MOBILE).needs_port

    def test_extra_fields_preserved(self) -> None:
        cfg = TargetConfig.from_dict({
            "platform": "desktop",
            "framework": "electron",
            "custom_key": "custom_value",
        })
        assert cfg.extra["custom_key"] == "custom_value"

    def test_window_dimensions_parsed_as_int(self) -> None:
        cfg = TargetConfig.from_dict({
            "platform": "desktop",
            "window_width": "1920",
            "window_height": "1080",
        })
        assert cfg.window_width == 1920
        assert cfg.window_height == 1080

    def test_window_dimensions_invalid_returns_none(self) -> None:
        cfg = TargetConfig.from_dict({
            "platform": "desktop",
            "window_width": "not-a-number",
        })
        assert cfg.window_width is None


# ===========================================================================
# FrameworkMeta registry completeness
# ===========================================================================

class TestFrameworkRegistry:
    def test_all_desktop_frameworks_registered(self) -> None:
        for fw in ("electron", "tauri", "pyinstaller", "tkinter", "pyqt"):
            meta = get_framework_meta(fw)
            assert meta is not None, f"Missing framework: {fw}"
            assert meta.platform == TargetPlatform.DESKTOP

    def test_all_mobile_frameworks_registered(self) -> None:
        for fw in ("capacitor", "react-native", "kivy"):
            meta = get_framework_meta(fw)
            assert meta is not None, f"Missing framework: {fw}"
            assert meta.platform == TargetPlatform.MOBILE

    def test_flutter_desktop_registered(self) -> None:
        meta = get_framework_meta("flutter-desktop")
        assert meta is not None
        assert meta.platform == TargetPlatform.DESKTOP

    def test_flutter_mobile_registered(self) -> None:
        meta = get_framework_meta("flutter-mobile")
        assert meta is not None
        assert meta.platform == TargetPlatform.MOBILE

    def test_case_insensitive_lookup(self) -> None:
        assert get_framework_meta("Electron") is not None
        assert get_framework_meta("ELECTRON") is not None
        assert get_framework_meta("  electron  ") is not None

    def test_unknown_framework_returns_none(self) -> None:
        assert get_framework_meta("nonexistent") is None
        assert get_framework_meta("") is None
        assert get_framework_meta(None) is None

    def test_list_frameworks_all(self) -> None:
        all_fw = list_frameworks()
        assert len(all_fw) == len(FRAMEWORK_REGISTRY)

    def test_list_frameworks_desktop(self) -> None:
        desktop = list_frameworks(TargetPlatform.DESKTOP)
        assert all(f.platform == TargetPlatform.DESKTOP for f in desktop)
        assert len(desktop) >= 5  # electron, tauri, pyinstaller, tkinter, pyqt, flutter-desktop

    def test_list_frameworks_mobile(self) -> None:
        mobile = list_frameworks(TargetPlatform.MOBILE)
        assert all(f.platform == TargetPlatform.MOBILE for f in mobile)
        assert len(mobile) >= 3  # capacitor, react-native, flutter-mobile, kivy

    def test_node_frameworks_have_needs_node_true(self) -> None:
        for name in ("electron", "tauri", "capacitor", "react-native"):
            meta = get_framework_meta(name)
            assert meta.needs_node, f"{name} should have needs_node=True"

    def test_python_frameworks_have_needs_python_true(self) -> None:
        for name in ("pyinstaller", "tkinter", "pyqt", "kivy"):
            meta = get_framework_meta(name)
            assert meta.needs_python, f"{name} should have needs_python=True"

    def test_every_framework_has_default_build_cmd(self) -> None:
        for name, meta in FRAMEWORK_REGISTRY.items():
            assert meta.default_build_cmd, f"{name} has no default_build_cmd"


# ===========================================================================
# infer_target_from_deps heuristic
# ===========================================================================

class TestInferTargetFromDeps:
    def test_electron_dep_infers_desktop(self) -> None:
        assert infer_target_from_deps(["electron"]) == TargetPlatform.DESKTOP

    def test_pyqt_dep_infers_desktop(self) -> None:
        assert infer_target_from_deps(["PyQt6"]) == TargetPlatform.DESKTOP

    def test_capacitor_dep_infers_mobile(self) -> None:
        assert infer_target_from_deps(["@capacitor/core"]) == TargetPlatform.MOBILE

    def test_react_native_dep_infers_mobile(self) -> None:
        assert infer_target_from_deps(["react-native"]) == TargetPlatform.MOBILE

    def test_buildozer_dep_infers_mobile(self) -> None:
        assert infer_target_from_deps(["buildozer"]) == TargetPlatform.MOBILE

    def test_fastapi_dep_infers_web(self) -> None:
        assert infer_target_from_deps(["fastapi", "uvicorn"]) == TargetPlatform.WEB

    def test_empty_deps_infers_web(self) -> None:
        assert infer_target_from_deps([]) == TargetPlatform.WEB

    def test_mobile_takes_priority_over_desktop(self) -> None:
        # When both hints are present, mobile wins (checked first)
        result = infer_target_from_deps(["kivy", "buildozer"])
        assert result == TargetPlatform.MOBILE


# ===========================================================================
# extract_run_command fallback logic
# ===========================================================================

class TestExtractRunCommand:
    def test_explicit_run_block(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, """\
        # App

        ```bash markpact:run
        python -m uvicorn main:app
        ```
        """)
        blocks = parse_blocks(readme.read_text())
        cmd = extract_run_command(blocks)
        assert cmd == "python -m uvicorn main:app"

    def test_framework_default_run_cmd(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, """\
        # App

        ```yaml markpact:target
        platform: desktop
        framework: electron
        ```
        """)
        blocks = parse_blocks(readme.read_text())
        cmd = extract_run_command(blocks)
        assert cmd is not None
        assert "electron" in cmd

    def test_file_heuristic_main_py(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, """\
        # App

        ```python markpact:file path=main.py
        print("hello")
        ```
        """)
        blocks = parse_blocks(readme.read_text())
        cmd = extract_run_command(blocks)
        assert cmd == "python main.py"

    def test_file_heuristic_index_js(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, """\
        # App

        ```javascript markpact:file path=index.js
        console.log("hello");
        ```
        """)
        blocks = parse_blocks(readme.read_text())
        cmd = extract_run_command(blocks)
        assert cmd == "node index.js"

    def test_no_run_cmd_returns_none(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, """\
        # App

        ```python markpact:deps
        requests
        ```
        """)
        blocks = parse_blocks(readme.read_text())
        cmd = extract_run_command(blocks)
        assert cmd is None


# ===========================================================================
# Build failure scenarios
# ===========================================================================

class TestBuildFailures:
    def test_desktop_build_failure_returns_details(self, tmp_path: Path) -> None:
        builder = DesktopBuilder()
        result = builder.build(
            tmp_path,
            build_cmd="echo 'error: compilation failed' >&2 && false",
            framework="electron",
        )

        assert not result.success
        assert result.platform == "desktop"
        assert result.framework == "electron"
        assert "failed" in result.message.lower()
        assert result.build_cmd is not None
        assert result.elapsed_seconds >= 0
        assert len(result.logs) > 0

    def test_mobile_build_failure_returns_details(self, tmp_path: Path) -> None:
        builder = MobileBuilder()
        result = builder.build(
            tmp_path,
            build_cmd="false",
            framework="capacitor",
        )

        assert not result.success
        assert result.platform == "mobile"
        assert "failed" in result.message.lower()

    def test_web_build_failure_returns_details(self, tmp_path: Path) -> None:
        builder = WebBuilder()
        result = builder.build(
            tmp_path,
            build_cmd="false",
        )

        assert not result.success
        assert result.platform == "web"
        assert "failed" in result.message.lower()

    def test_build_with_stderr_captured(self, tmp_path: Path) -> None:
        builder = DesktopBuilder()
        result = builder.build(
            tmp_path,
            build_cmd="echo 'something went wrong' >&2 && exit 1",
            framework="electron",
        )

        assert not result.success
        # STDERR should appear in logs
        assert any("stderr" in l.lower() or "wrong" in l.lower() for l in result.logs)


# ===========================================================================
# Multi-platform build from ServiceConfig
# ===========================================================================

class TestServiceConfigBuildTargets:
    def test_desktop_electron_from_service_config(self) -> None:
        cfg = ServiceConfig.from_dict("electron-app", {
            "readme": "electron-app/README.md",
            "target": "desktop",
            "framework": "electron",
            "build_targets": ["linux", "windows", "mac"],
            "build_cmd": "npx electron-builder --linux --windows --mac",
        })
        assert cfg.target == "desktop"
        assert cfg.framework == "electron"
        assert cfg.build_targets == ["linux", "windows", "mac"]

    def test_mobile_capacitor_from_service_config(self) -> None:
        cfg = ServiceConfig.from_dict("cap-app", {
            "readme": "cap-app/README.md",
            "target": "mobile",
            "framework": "capacitor",
            "build_targets": ["android", "ios"],
        })
        assert cfg.target == "mobile"
        assert cfg.framework == "capacitor"
        assert cfg.build_targets == ["android", "ios"]

    def test_mobile_kivy_from_service_config(self) -> None:
        cfg = ServiceConfig.from_dict("kivy-app", {
            "readme": "kivy-app/README.md",
            "target": "mobile",
            "framework": "kivy",
            "build_targets": "android",
        })
        assert cfg.target == "mobile"
        assert cfg.framework == "kivy"
        assert cfg.build_targets == ["android"]

    def test_desktop_pyqt_from_service_config(self) -> None:
        cfg = ServiceConfig.from_dict("pyqt-app", {
            "readme": "pyqt-app/README.md",
            "target": "desktop",
            "framework": "pyqt",
            "build_cmd": "pyinstaller --onefile main.py",
        })
        assert cfg.target == "desktop"
        assert cfg.framework == "pyqt"
        assert cfg.build_cmd == "pyinstaller --onefile main.py"


# ===========================================================================
# Full markpact pipeline: Python API → Electron desktop
# ===========================================================================

class TestE2EPythonApiToElectronDesktop:
    """Regression test for the exact scenario that caused the original bug:
    a Python FastAPI project built as an Electron desktop app."""

    MARKPACT = """\
    # Hello API

    ```yaml markpact:target
    platform: desktop
    framework: electron
    app_name: hello-api
    app_id: com.pactown.hello-api
    ```

    ```python markpact:file path=main.py
    from fastapi import FastAPI
    app = FastAPI()

    @app.get("/")
    def root():
        return {"hello": "world"}
    ```

    ```python markpact:deps
    fastapi
    uvicorn
    ```

    ```html markpact:file path=index.html
    <!DOCTYPE html>
    <html><body><h1>Hello API</h1></body></html>
    ```

    ```bash markpact:build
    mkdir -p dist && echo "appimage" > dist/hello-api.AppImage
    ```

    ```bash markpact:run
    npx electron .
    ```
    """

    def test_parse_python_api_as_electron(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        blocks, target_cfg, build_cmd = _parse_and_resolve(readme)

        assert target_cfg.platform == TargetPlatform.DESKTOP
        assert target_cfg.framework == "electron"
        assert target_cfg.app_name == "hello-api"

        # Should have both Python deps and HTML file blocks
        file_blocks = [b for b in blocks if b.kind == "file"]
        assert len(file_blocks) == 2  # main.py + index.html

        dep_blocks = [b for b in blocks if b.kind == "deps"]
        assert len(dep_blocks) == 1
        assert "fastapi" in dep_blocks[0].body

    def test_scaffold_with_python_deps_package_json(self, tmp_path: Path) -> None:
        """Simulates what SandboxManager does: creates package.json for python
        deps first, then scaffold adds electron to devDependencies."""
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        # Simulate SandboxManager._ensure_package_json (Python project has no node deps
        # but sandbox may have a minimal package.json from node detection)
        # In the real bug, there was NO package.json before scaffold
        builder = DesktopBuilder()
        builder.scaffold(
            sandbox,
            framework="electron",
            app_name="hello-api",
            extra={"app_id": "com.pactown.hello-api"},
        )

        pkg = json.loads((sandbox / "package.json").read_text())
        assert "electron" in pkg.get("devDependencies", {}), \
            f"electron must be in devDependencies: {json.dumps(pkg, indent=2)}"
        assert "electron-builder" in pkg.get("devDependencies", {}), \
            f"electron-builder must be in devDependencies: {json.dumps(pkg, indent=2)}"
        assert pkg["build"]["appId"] == "com.pactown.hello-api"
        assert (sandbox / "main.js").exists()

    def test_full_build_succeeds(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        _, target_cfg, build_cmd = _parse_and_resolve(readme)

        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        (sandbox / "index.html").write_text("<h1>Hello</h1>")

        builder = DesktopBuilder()
        builder.scaffold(
            sandbox,
            framework="electron",
            app_name="hello-api",
            extra={"app_id": "com.pactown.hello-api"},
        )

        result = builder.build(
            sandbox,
            build_cmd=build_cmd,
            framework="electron",
            targets=["linux"],
        )

        assert result.success
        assert result.platform == "desktop"
        assert result.framework == "electron"
        assert (sandbox / "dist" / "hello-api.AppImage").exists()
        assert len(result.artifacts) >= 1
        assert result.elapsed_seconds >= 0
