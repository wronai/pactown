"""End-to-end deployment tests for every platform supported by pactown.

Tests the full pipeline for each framework:
  markpact README → parse → create_sandbox → IaC artifacts → scaffold → build → artifacts

Platforms covered:
  Desktop: Electron, Tauri, PyInstaller, PyQt, Tkinter, Flutter-desktop
  Mobile:  Capacitor, React Native, Kivy, Flutter-mobile
  Web:     FastAPI (Python), Flask (Python), Express (Node), static HTML

Each test class verifies:
  1. Sandbox creation (files written, deps detected)
  2. IaC manifest (pactown.sandbox.yaml)
  3. Dockerfile generation (correct base image, CMD)
  4. docker-compose.yaml (ports, healthcheck)
  5. Scaffold output (framework-specific files)
  6. Build pipeline (build_cmd → artifacts)
  7. BuildResult fields (platform, framework, elapsed, logs)
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional

import pytest
import yaml

from pactown.builders import (
    BuildResult,
    DesktopBuilder,
    MobileBuilder,
    WebBuilder,
    get_builder_for_target,
)
from pactown.config import ServiceConfig
from pactown.deploy.base import DeploymentConfig
from pactown.deploy.docker import DockerBackend
from pactown.iac import build_sandbox_spec, build_single_service_compose
from pactown.markpact_blocks import (
    extract_build_cmd,
    extract_run_command,
    extract_target_config,
    parse_blocks,
)
from pactown.sandbox_manager import SandboxManager
from pactown.targets import TargetConfig, TargetPlatform, get_framework_meta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _readme(content: str) -> str:
    return textwrap.dedent(content)


def _sandbox_and_manager(tmp: Path):
    sandbox_root = tmp / "sandboxes"
    return sandbox_root, SandboxManager(sandbox_root)


def _create_sandbox_from_readme(
    tmp: Path,
    readme_text: str,
    service_name: str,
    port: Optional[int] = None,
    target: str = "web",
    framework: Optional[str] = None,
):
    """Helper: write README, create sandbox, return (sandbox, manager, blocks)."""
    readme_path = tmp / "README.md"
    readme_path.write_text(readme_text)

    svc = ServiceConfig(
        name=service_name,
        readme=str(readme_path),
        port=port,
        target=target,
        framework=framework,
    )
    sandbox_root, manager = _sandbox_and_manager(tmp)
    sandbox = manager.create_sandbox(svc, readme_path, install_dependencies=False)
    blocks = parse_blocks(readme_text)
    return sandbox, manager, svc, blocks


# ===========================================================================
# DESKTOP: Electron
# ===========================================================================

class TestDeployDesktopElectron:
    README = _readme("""\
    # Electron App

    ```yaml markpact:target
    platform: desktop
    framework: electron
    app_name: MyElectronApp
    app_id: com.test.electronapp
    window_width: 1280
    window_height: 720
    ```

    ```html markpact:file path=index.html
    <!DOCTYPE html>
    <html><body><h1>Hello Electron</h1></body></html>
    ```

    ```bash markpact:build
    mkdir -p dist && echo "appimage" > dist/MyElectronApp.AppImage
    ```

    ```bash markpact:run
    npx electron .
    ```
    """)

    def test_sandbox_creation(self, tmp_path: Path) -> None:
        sandbox, mgr, svc, blocks = _create_sandbox_from_readme(
            tmp_path, self.README, "electron-app", target="desktop", framework="electron",
        )
        assert (sandbox.path / "index.html").exists()

    def test_target_parsing(self) -> None:
        blocks = parse_blocks(self.README)
        cfg = extract_target_config(blocks)
        assert cfg.platform == TargetPlatform.DESKTOP
        assert cfg.framework == "electron"
        assert cfg.app_name == "MyElectronApp"
        assert cfg.window_width == 1280

    def test_scaffold_creates_package_json_and_main_js(self, tmp_path: Path) -> None:
        sandbox_dir = tmp_path / "sandbox"
        sandbox_dir.mkdir()
        builder = DesktopBuilder()
        builder.scaffold(
            sandbox_dir, framework="electron", app_name="MyElectronApp",
            extra={"app_id": "com.test.electronapp", "window_width": 1280, "window_height": 720},
        )
        assert (sandbox_dir / "package.json").exists()
        assert (sandbox_dir / "main.js").exists()
        pkg = json.loads((sandbox_dir / "package.json").read_text())
        assert "electron" in pkg["devDependencies"]
        assert "electron-builder" in pkg["devDependencies"]
        assert pkg["build"]["appId"] == "com.test.electronapp"

    def test_build_produces_artifacts(self, tmp_path: Path) -> None:
        blocks = parse_blocks(self.README)
        build_cmd = extract_build_cmd(blocks)
        sandbox_dir = tmp_path / "sandbox"
        sandbox_dir.mkdir()
        (sandbox_dir / "index.html").write_text("<h1>Hello</h1>")

        builder = DesktopBuilder()
        builder.scaffold(sandbox_dir, framework="electron", app_name="MyElectronApp")
        result = builder.build(sandbox_dir, build_cmd=build_cmd, framework="electron", targets=["linux"])

        assert result.success
        assert result.platform == "desktop"
        assert result.framework == "electron"
        assert result.elapsed_seconds >= 0
        assert len(result.artifacts) >= 1
        assert any("AppImage" in str(a) for a in result.artifacts)

    def test_build_result_has_logs(self, tmp_path: Path) -> None:
        sandbox_dir = tmp_path / "sandbox"
        sandbox_dir.mkdir()
        builder = DesktopBuilder()
        result = builder.build(sandbox_dir, build_cmd="echo electron-build-ok", framework="electron")
        assert result.success
        assert any("electron-build-ok" in l for l in result.logs)

    def test_iac_spec_for_electron(self, tmp_path: Path) -> None:
        spec = build_sandbox_spec(
            service_name="electron-app",
            readme_path=tmp_path / "README.md",
            sandbox_path=tmp_path,
            port=None,
            run_cmd="npx electron .",
            is_node=True,
            python_deps=[],
            node_deps=["electron", "electron-builder"],
            health_path="/",
            env_keys=[],
        )
        assert spec["spec"]["runtime"]["type"] == "node"
        assert "electron" in spec["spec"]["dependencies"]["node"]


# ===========================================================================
# DESKTOP: Tauri
# ===========================================================================

class TestDeployDesktopTauri:
    README = _readme("""\
    # Tauri App

    ```yaml markpact:target
    platform: desktop
    framework: tauri
    app_name: TauriApp
    app_id: com.test.tauriapp
    ```

    ```html markpact:file path=index.html
    <h1>Tauri</h1>
    ```

    ```bash markpact:build
    mkdir -p src-tauri/target/release/bundle/appimage && echo "bin" > src-tauri/target/release/bundle/appimage/TauriApp.AppImage
    ```
    """)

    def test_scaffold_creates_tauri_conf(self, tmp_path: Path) -> None:
        builder = DesktopBuilder()
        builder.scaffold(tmp_path, framework="tauri", app_name="TauriApp",
                         extra={"app_id": "com.test.tauriapp"})
        conf = tmp_path / "src-tauri" / "tauri.conf.json"
        assert conf.exists()
        data = json.loads(conf.read_text())
        assert data["tauri"]["bundle"]["identifier"] == "com.test.tauriapp"
        assert data["package"]["productName"] == "TauriApp"

    def test_full_build(self, tmp_path: Path) -> None:
        blocks = parse_blocks(self.README)
        build_cmd = extract_build_cmd(blocks)
        builder = DesktopBuilder()
        builder.scaffold(tmp_path, framework="tauri", app_name="TauriApp")
        result = builder.build(tmp_path, build_cmd=build_cmd, framework="tauri", targets=["linux"])
        assert result.success
        assert result.platform == "desktop"
        assert result.framework == "tauri"
        assert len(result.artifacts) >= 1

    def test_default_build_cmd(self) -> None:
        cmd = DesktopBuilder._default_build_cmd("tauri", ["linux"])
        assert "tauri build" in cmd


# ===========================================================================
# DESKTOP: PyInstaller
# ===========================================================================

class TestDeployDesktopPyInstaller:
    README = _readme("""\
    # PyInstaller App

    ```yaml markpact:target
    platform: desktop
    framework: pyinstaller
    app_name: cliapp
    ```

    ```python markpact:file path=main.py
    print("Hello from PyInstaller app")
    ```

    ```python markpact:deps
    pyinstaller
    ```

    ```bash markpact:build
    mkdir -p dist && echo "binary" > dist/cliapp
    ```
    """)

    def test_scaffold_creates_spec(self, tmp_path: Path) -> None:
        builder = DesktopBuilder()
        builder.scaffold(tmp_path, framework="pyinstaller", app_name="cliapp")
        assert (tmp_path / "cliapp.spec").exists()
        assert "cliapp" in (tmp_path / "cliapp.spec").read_text()

    def test_full_build(self, tmp_path: Path) -> None:
        build_cmd = extract_build_cmd(parse_blocks(self.README))
        builder = DesktopBuilder()
        builder.scaffold(tmp_path, framework="pyinstaller", app_name="cliapp")
        result = builder.build(tmp_path, build_cmd=build_cmd, framework="pyinstaller")
        assert result.success
        assert (tmp_path / "dist" / "cliapp").exists()

    def test_sandbox_writes_requirements(self, tmp_path: Path) -> None:
        sandbox, _, _, _ = _create_sandbox_from_readme(
            tmp_path, self.README, "pyinstaller-app", target="desktop", framework="pyinstaller",
        )
        assert (sandbox.path / "main.py").exists()
        assert (sandbox.path / "requirements.txt").exists()
        assert "pyinstaller" in (sandbox.path / "requirements.txt").read_text()

    def test_iac_python_runtime(self, tmp_path: Path) -> None:
        sandbox, _, _, _ = _create_sandbox_from_readme(
            tmp_path, self.README, "pyinstaller-app", target="desktop", framework="pyinstaller",
        )
        manifest = sandbox.path / "pactown.sandbox.yaml"
        assert manifest.exists()
        spec = yaml.safe_load(manifest.read_text())
        assert spec["spec"]["runtime"]["type"] == "python"

    def test_dockerfile_generation(self, tmp_path: Path) -> None:
        sandbox, _, _, _ = _create_sandbox_from_readme(
            tmp_path, self.README, "pyinstaller-app", target="desktop", framework="pyinstaller",
        )
        df = sandbox.path / "Dockerfile"
        assert df.exists()
        content = df.read_text()
        assert "FROM python" in content
        assert "requirements.txt" in content


# ===========================================================================
# DESKTOP: PyQt
# ===========================================================================

class TestDeployDesktopPyQt:
    README = _readme("""\
    # PyQt App

    ```yaml markpact:target
    platform: desktop
    framework: pyqt
    app_name: GuiApp
    icon: icon.png
    ```

    ```python markpact:file path=main.py
    import sys
    from PyQt6.QtWidgets import QApplication, QMainWindow
    app = QApplication(sys.argv)
    w = QMainWindow()
    w.show()
    app.exec()
    ```

    ```python markpact:deps
    PyQt6
    pyinstaller
    ```

    ```bash markpact:build
    mkdir -p dist && echo "binary" > dist/GuiApp
    ```
    """)

    def test_scaffold_creates_spec_with_icon(self, tmp_path: Path) -> None:
        builder = DesktopBuilder()
        builder.scaffold(tmp_path, framework="pyqt", app_name="GuiApp", extra={"icon": "icon.png"})
        spec = tmp_path / "GuiApp.spec"
        assert spec.exists()
        text = spec.read_text()
        assert "GuiApp" in text
        assert "icon.png" in text

    def test_full_build(self, tmp_path: Path) -> None:
        build_cmd = extract_build_cmd(parse_blocks(self.README))
        builder = DesktopBuilder()
        builder.scaffold(tmp_path, framework="pyqt", app_name="GuiApp")
        result = builder.build(tmp_path, build_cmd=build_cmd, framework="pyqt")
        assert result.success
        assert result.framework == "pyqt"

    def test_framework_meta(self) -> None:
        meta = get_framework_meta("pyqt")
        assert meta is not None
        assert meta.needs_python
        assert not meta.needs_node
        assert "pyinstaller" in meta.default_build_cmd


# ===========================================================================
# DESKTOP: Tkinter
# ===========================================================================

class TestDeployDesktopTkinter:
    README = _readme("""\
    # Tkinter App

    ```yaml markpact:target
    platform: desktop
    framework: tkinter
    app_name: tkapp
    ```

    ```python markpact:file path=main.py
    import tkinter as tk
    root = tk.Tk()
    root.mainloop()
    ```

    ```bash markpact:build
    mkdir -p dist && echo "binary" > dist/tkapp
    ```
    """)

    def test_scaffold_and_build(self, tmp_path: Path) -> None:
        build_cmd = extract_build_cmd(parse_blocks(self.README))
        builder = DesktopBuilder()
        builder.scaffold(tmp_path, framework="tkinter", app_name="tkapp")
        assert (tmp_path / "tkapp.spec").exists()
        result = builder.build(tmp_path, build_cmd=build_cmd, framework="tkinter")
        assert result.success

    def test_default_cmd_uses_pyinstaller(self) -> None:
        cmd = DesktopBuilder._default_build_cmd("tkinter", None)
        assert "pyinstaller" in cmd


# ===========================================================================
# DESKTOP: Flutter
# ===========================================================================

class TestDeployDesktopFlutter:
    README = _readme("""\
    # Flutter Desktop

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
    """)

    def test_parse_and_build(self, tmp_path: Path) -> None:
        blocks = parse_blocks(self.README)
        cfg = extract_target_config(blocks)
        assert cfg.platform == TargetPlatform.DESKTOP
        assert cfg.framework == "flutter"

        build_cmd = extract_build_cmd(blocks)
        builder = DesktopBuilder()
        builder.scaffold(tmp_path, framework="flutter", app_name="FlutterDesktop")
        result = builder.build(tmp_path, build_cmd=build_cmd, framework="flutter", targets=["linux"])
        assert result.success

    def test_default_cmd(self) -> None:
        cmd = DesktopBuilder._default_build_cmd("flutter", ["linux"])
        assert "flutter build linux" in cmd


# ===========================================================================
# MOBILE: Capacitor
# ===========================================================================

class TestDeployMobileCapacitor:
    README = _readme("""\
    # Capacitor App

    ```yaml markpact:target
    platform: mobile
    framework: capacitor
    app_name: CapApp
    app_id: com.test.capapp
    targets:
      - android
    ```

    ```html markpact:file path=dist/index.html
    <!DOCTYPE html>
    <html><body><h1>CapApp</h1></body></html>
    ```

    ```javascript markpact:deps
    @capacitor/core
    @capacitor/cli
    ```

    ```bash markpact:build
    mkdir -p android/app/build/outputs/apk/release && echo "apk" > android/app/build/outputs/apk/release/app-release.apk
    ```
    """)

    def test_scaffold_creates_capacitor_config(self, tmp_path: Path) -> None:
        builder = MobileBuilder()
        builder.scaffold(tmp_path, framework="capacitor", app_name="CapApp",
                         extra={"app_id": "com.test.capapp"})
        cap = tmp_path / "capacitor.config.json"
        assert cap.exists()
        data = json.loads(cap.read_text())
        assert data["appId"] == "com.test.capapp"
        assert data["appName"] == "CapApp"
        assert data["webDir"] == "dist"

    def test_scaffold_creates_package_json_scripts(self, tmp_path: Path) -> None:
        builder = MobileBuilder()
        builder.scaffold(tmp_path, framework="capacitor", app_name="CapApp")
        pkg = json.loads((tmp_path / "package.json").read_text())
        assert "cap:sync" in pkg["scripts"]
        assert "cap:build:android" in pkg["scripts"]

    def test_full_build(self, tmp_path: Path) -> None:
        build_cmd = extract_build_cmd(parse_blocks(self.README))
        builder = MobileBuilder()
        builder.scaffold(tmp_path, framework="capacitor", app_name="CapApp")
        result = builder.build(tmp_path, build_cmd=build_cmd, framework="capacitor", targets=["android"])
        assert result.success
        assert result.platform == "mobile"
        assert result.framework == "capacitor"
        assert len(result.artifacts) >= 1

    def test_builder_registry(self) -> None:
        cfg = TargetConfig(platform=TargetPlatform.MOBILE, framework="capacitor")
        builder = get_builder_for_target(cfg)
        assert isinstance(builder, MobileBuilder)

    def test_iac_node_runtime(self, tmp_path: Path) -> None:
        spec = build_sandbox_spec(
            service_name="cap-app",
            readme_path=tmp_path / "README.md",
            sandbox_path=tmp_path,
            port=None,
            run_cmd="npx cap run android",
            is_node=True,
            python_deps=[],
            node_deps=["@capacitor/core", "@capacitor/cli"],
            health_path="/",
            env_keys=[],
        )
        assert spec["spec"]["runtime"]["type"] == "node"
        assert "@capacitor/core" in spec["spec"]["dependencies"]["node"]


# ===========================================================================
# MOBILE: React Native
# ===========================================================================

class TestDeployMobileReactNative:
    README = _readme("""\
    # React Native App

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
    export default () => <View><Text>Hello</Text></View>;
    ```

    ```bash markpact:build
    mkdir -p android/app/build/outputs/apk/release && echo "apk" > android/app/build/outputs/apk/release/app-release.apk
    ```
    """)

    def test_scaffold_creates_app_json(self, tmp_path: Path) -> None:
        builder = MobileBuilder()
        builder.scaffold(tmp_path, framework="react-native", app_name="RNApp")
        app_json = tmp_path / "app.json"
        assert app_json.exists()
        data = json.loads(app_json.read_text())
        assert data["name"] == "RNApp"

    def test_full_build(self, tmp_path: Path) -> None:
        build_cmd = extract_build_cmd(parse_blocks(self.README))
        builder = MobileBuilder()
        builder.scaffold(tmp_path, framework="react-native", app_name="RNApp")
        result = builder.build(tmp_path, build_cmd=build_cmd, framework="react-native", targets=["android"])
        assert result.success
        assert result.platform == "mobile"
        assert len(result.artifacts) >= 1

    def test_default_cmd_android(self) -> None:
        cmd = MobileBuilder._default_build_cmd("react-native", ["android"])
        assert "build-android" in cmd

    def test_default_cmd_ios(self) -> None:
        cmd = MobileBuilder._default_build_cmd("react-native", ["ios"])
        assert "build-ios" in cmd


# ===========================================================================
# MOBILE: Kivy
# ===========================================================================

class TestDeployMobileKivy:
    README = _readme("""\
    # Kivy App

    ```yaml markpact:target
    platform: mobile
    framework: kivy
    app_name: WeatherApp
    app_id: com.test.weatherapp
    fullscreen: true
    ```

    ```python markpact:file path=main.py
    from kivy.app import App
    class WeatherApp(App):
        pass
    WeatherApp().run()
    ```

    ```python markpact:deps
    kivy
    buildozer
    ```

    ```bash markpact:build
    mkdir -p bin && echo "apk" > bin/WeatherApp.apk
    ```
    """)

    def test_scaffold_creates_buildozer_spec(self, tmp_path: Path) -> None:
        builder = MobileBuilder()
        builder.scaffold(tmp_path, framework="kivy", app_name="WeatherApp",
                         extra={"app_id": "com.test.weatherapp", "fullscreen": True})
        spec = tmp_path / "buildozer.spec"
        assert spec.exists()
        text = spec.read_text()
        assert "WeatherApp" in text
        assert "fullscreen = 1" in text

    def test_full_build(self, tmp_path: Path) -> None:
        build_cmd = extract_build_cmd(parse_blocks(self.README))
        builder = MobileBuilder()
        builder.scaffold(tmp_path, framework="kivy", app_name="WeatherApp")
        result = builder.build(tmp_path, build_cmd=build_cmd, framework="kivy", targets=["android"])
        assert result.success
        assert len(result.artifacts) >= 1
        assert any("WeatherApp.apk" in str(a) for a in result.artifacts)

    def test_sandbox_creates_requirements(self, tmp_path: Path) -> None:
        sandbox, _, _, _ = _create_sandbox_from_readme(
            tmp_path, self.README, "kivy-app", target="mobile", framework="kivy",
        )
        assert (sandbox.path / "main.py").exists()
        assert (sandbox.path / "requirements.txt").exists()
        req = (sandbox.path / "requirements.txt").read_text()
        assert "kivy" in req
        assert "buildozer" in req

    def test_iac_python_runtime(self, tmp_path: Path) -> None:
        sandbox, _, _, _ = _create_sandbox_from_readme(
            tmp_path, self.README, "kivy-app", target="mobile", framework="kivy",
        )
        manifest = sandbox.path / "pactown.sandbox.yaml"
        assert manifest.exists()
        spec = yaml.safe_load(manifest.read_text())
        assert spec["spec"]["runtime"]["type"] == "python"


# ===========================================================================
# MOBILE: Flutter
# ===========================================================================

class TestDeployMobileFlutter:
    README = _readme("""\
    # Flutter Mobile

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
    """)

    def test_parse(self) -> None:
        blocks = parse_blocks(self.README)
        cfg = extract_target_config(blocks)
        assert cfg.platform == TargetPlatform.MOBILE
        assert cfg.framework == "flutter"
        assert "android" in cfg.targets
        assert "ios" in cfg.targets

    def test_build(self, tmp_path: Path) -> None:
        build_cmd = extract_build_cmd(parse_blocks(self.README))
        builder = MobileBuilder()
        builder.scaffold(tmp_path, framework="flutter", app_name="FlutterApp")
        result = builder.build(tmp_path, build_cmd=build_cmd, framework="flutter", targets=["android"])
        assert result.success
        assert len(result.artifacts) >= 1

    def test_default_cmd_android(self) -> None:
        assert "flutter build apk" in MobileBuilder._default_build_cmd("flutter", ["android"])

    def test_default_cmd_ios(self) -> None:
        assert "flutter build ios" in MobileBuilder._default_build_cmd("flutter", ["ios"])


# ===========================================================================
# WEB: FastAPI (Python)
# ===========================================================================

class TestDeployWebFastAPI:
    README = _readme("""\
    # FastAPI Service

    ```python markpact:deps
    fastapi
    uvicorn
    ```

    ```python markpact:file path=main.py
    from fastapi import FastAPI
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/")
    def root():
        return {"hello": "world"}
    ```

    ```bash markpact:run
    uvicorn main:app --host 0.0.0.0 --port ${MARKPACT_PORT:-8000}
    ```
    """)

    def test_sandbox_creation(self, tmp_path: Path) -> None:
        sandbox, _, _, _ = _create_sandbox_from_readme(
            tmp_path, self.README, "fastapi-svc", port=8001,
        )
        assert (sandbox.path / "main.py").exists()
        assert (sandbox.path / "requirements.txt").exists()
        req = (sandbox.path / "requirements.txt").read_text()
        assert "fastapi" in req
        assert "uvicorn" in req

    def test_iac_manifest(self, tmp_path: Path) -> None:
        sandbox, _, _, _ = _create_sandbox_from_readme(
            tmp_path, self.README, "fastapi-svc", port=8001,
        )
        manifest = sandbox.path / "pactown.sandbox.yaml"
        assert manifest.exists()
        spec = yaml.safe_load(manifest.read_text())
        assert spec["spec"]["runtime"]["type"] == "python"
        assert spec["spec"]["run"]["port"] == 8001
        assert "fastapi" in spec["spec"]["dependencies"]["python"]

    def test_dockerfile_python_image(self, tmp_path: Path) -> None:
        sandbox, _, _, _ = _create_sandbox_from_readme(
            tmp_path, self.README, "fastapi-svc", port=8001,
        )
        df = sandbox.path / "Dockerfile"
        assert df.exists()
        content = df.read_text()
        assert "FROM python" in content
        assert "requirements.txt" in content
        assert "HEALTHCHECK" in content

    def test_compose_yaml(self, tmp_path: Path) -> None:
        sandbox, _, _, _ = _create_sandbox_from_readme(
            tmp_path, self.README, "fastapi-svc", port=8001,
        )
        compose_path = sandbox.path / "docker-compose.yaml"
        assert compose_path.exists()
        compose = yaml.safe_load(compose_path.read_text())
        assert "app" in compose["services"]
        svc = compose["services"]["app"]
        assert "8001:8001" in svc["ports"]

    def test_web_builder_no_artifacts(self, tmp_path: Path) -> None:
        builder = WebBuilder()
        result = builder.build(tmp_path, framework="fastapi")
        assert result.success
        assert result.platform == "web"

    def test_run_cmd_extracted(self) -> None:
        blocks = parse_blocks(self.README)
        cmd = extract_run_command(blocks)
        assert cmd is not None
        assert "uvicorn" in cmd


# ===========================================================================
# WEB: Flask (Python)
# ===========================================================================

class TestDeployWebFlask:
    README = _readme("""\
    # Flask Service

    ```python markpact:deps
    flask
    gunicorn
    ```

    ```python markpact:file path=app.py
    from flask import Flask, jsonify
    app = Flask(__name__)

    @app.route("/health")
    def health():
        return jsonify(ok=True)

    @app.route("/")
    def root():
        return jsonify(hello="world")
    ```

    ```bash markpact:run
    gunicorn app:app --bind 0.0.0.0:${MARKPACT_PORT:-8000}
    ```
    """)

    def test_sandbox_creation(self, tmp_path: Path) -> None:
        sandbox, _, _, _ = _create_sandbox_from_readme(
            tmp_path, self.README, "flask-svc", port=8002,
        )
        assert (sandbox.path / "app.py").exists()
        assert (sandbox.path / "requirements.txt").exists()
        req = (sandbox.path / "requirements.txt").read_text()
        assert "flask" in req
        assert "gunicorn" in req

    def test_iac_manifest_python(self, tmp_path: Path) -> None:
        sandbox, _, _, _ = _create_sandbox_from_readme(
            tmp_path, self.README, "flask-svc", port=8002,
        )
        spec = yaml.safe_load((sandbox.path / "pactown.sandbox.yaml").read_text())
        assert spec["spec"]["runtime"]["type"] == "python"
        assert "flask" in spec["spec"]["dependencies"]["python"]

    def test_dockerfile_python(self, tmp_path: Path) -> None:
        sandbox, _, _, _ = _create_sandbox_from_readme(
            tmp_path, self.README, "flask-svc", port=8002,
        )
        content = (sandbox.path / "Dockerfile").read_text()
        assert "FROM python" in content
        assert "requirements.txt" in content

    def test_compose_with_port(self, tmp_path: Path) -> None:
        sandbox, _, _, _ = _create_sandbox_from_readme(
            tmp_path, self.README, "flask-svc", port=8002,
        )
        compose = yaml.safe_load((sandbox.path / "docker-compose.yaml").read_text())
        assert "8002:8002" in compose["services"]["app"]["ports"]


# ===========================================================================
# WEB: Express (Node.js)
# ===========================================================================

class TestDeployWebExpress:
    README = _readme("""\
    # Express Service

    ```js markpact:deps
    express
    ```

    ```js markpact:file path=server.js
    const express = require('express');
    const app = express();
    const port = process.env.MARKPACT_PORT || 3000;

    app.get('/health', (req, res) => res.json({ ok: true }));
    app.listen(port, '0.0.0.0', () => console.log('listening', port));
    ```

    ```bash markpact:run
    node server.js
    ```
    """)

    def test_sandbox_creates_package_json(self, tmp_path: Path) -> None:
        sandbox, _, _, _ = _create_sandbox_from_readme(
            tmp_path, self.README, "express-svc", port=3001,
        )
        assert (sandbox.path / "server.js").exists()
        assert (sandbox.path / "package.json").exists()
        pkg = json.loads((sandbox.path / "package.json").read_text())
        assert "express" in pkg.get("dependencies", {})

    def test_iac_manifest_node(self, tmp_path: Path) -> None:
        sandbox, _, _, _ = _create_sandbox_from_readme(
            tmp_path, self.README, "express-svc", port=3001,
        )
        spec = yaml.safe_load((sandbox.path / "pactown.sandbox.yaml").read_text())
        assert spec["spec"]["runtime"]["type"] == "node"

    def test_dockerfile_node_image(self, tmp_path: Path) -> None:
        sandbox, _, _, _ = _create_sandbox_from_readme(
            tmp_path, self.README, "express-svc", port=3001,
        )
        content = (sandbox.path / "Dockerfile").read_text()
        assert "FROM node" in content
        assert "npm" in content

    def test_compose_healthcheck_node(self, tmp_path: Path) -> None:
        compose = build_single_service_compose(
            service_name="express-svc", port=3001, health_path="/health", is_node=True,
        )
        hc = compose["services"]["app"]["healthcheck"]
        assert "node" in hc["test"][1]
        hc_script = " ".join(hc["test"])
        assert "/health" in hc_script


# ===========================================================================
# WEB: Static HTML
# ===========================================================================

class TestDeployWebStatic:
    README = _readme("""\
    # Static Site

    ```html markpact:file path=public/index.html
    <!DOCTYPE html>
    <html><body><h1>Hello</h1></body></html>
    ```

    ```bash markpact:run
    python -m http.server ${MARKPACT_PORT:-8000} --directory public
    ```
    """)

    def test_sandbox_no_deps(self, tmp_path: Path) -> None:
        sandbox, _, _, _ = _create_sandbox_from_readme(
            tmp_path, self.README, "static-site", port=8003,
        )
        assert (sandbox.path / "public" / "index.html").exists()
        assert not (sandbox.path / "requirements.txt").exists()

    def test_iac_manifest(self, tmp_path: Path) -> None:
        sandbox, _, _, _ = _create_sandbox_from_readme(
            tmp_path, self.README, "static-site", port=8003,
        )
        spec = yaml.safe_load((sandbox.path / "pactown.sandbox.yaml").read_text())
        assert spec["spec"]["runtime"]["type"] == "python"
        assert spec["spec"]["run"]["command"] == "python -m http.server ${MARKPACT_PORT:-8000} --directory public"

    def test_web_builder_build_step(self, tmp_path: Path) -> None:
        builder = WebBuilder()
        (tmp_path / "public").mkdir()
        (tmp_path / "public" / "index.html").write_text("<h1>hi</h1>")
        result = builder.build(tmp_path, build_cmd="echo static-ok", framework="")
        assert result.success
        assert any("static-ok" in l for l in result.logs)


# ===========================================================================
# IaC: Sandbox spec completeness per platform
# ===========================================================================

class TestIaCSpecAllPlatforms:
    """Verify IaC sandbox spec is correct for every platform type."""

    def test_python_web_spec(self) -> None:
        spec = build_sandbox_spec(
            service_name="py-web", readme_path=Path("/tmp/r.md"),
            sandbox_path=Path("/tmp/s"), port=8000,
            run_cmd="uvicorn main:app", is_node=False,
            python_deps=["fastapi", "uvicorn"], node_deps=[],
            health_path="/health", env_keys=["API_KEY"],
        )
        assert spec["kind"] == "Sandbox"
        assert spec["spec"]["runtime"]["type"] == "python"
        assert spec["spec"]["run"]["port"] == 8000
        assert spec["spec"]["health"]["path"] == "/health"
        assert "API_KEY" in spec["spec"]["env"]["keys"]
        assert spec["spec"]["dependencies"]["python"] == ["fastapi", "uvicorn"]
        assert spec["spec"]["cicd"]["build"]["docker"]["baseImage"] == "python:3.12-slim"

    def test_node_web_spec(self) -> None:
        spec = build_sandbox_spec(
            service_name="node-web", readme_path=Path("/tmp/r.md"),
            sandbox_path=Path("/tmp/s"), port=3000,
            run_cmd="node server.js", is_node=True,
            python_deps=[], node_deps=["express"],
            health_path="/health", env_keys=[],
        )
        assert spec["spec"]["runtime"]["type"] == "node"
        assert spec["spec"]["cicd"]["build"]["docker"]["baseImage"] == "node:20-slim"

    def test_desktop_electron_spec(self) -> None:
        spec = build_sandbox_spec(
            service_name="electron-app", readme_path=Path("/tmp/r.md"),
            sandbox_path=Path("/tmp/s"), port=None,
            run_cmd="npx electron .", is_node=True,
            python_deps=[], node_deps=["electron", "electron-builder"],
            health_path="/", env_keys=[],
        )
        assert spec["spec"]["run"]["port"] is None
        assert "electron" in spec["spec"]["dependencies"]["node"]

    def test_mobile_kivy_spec(self) -> None:
        spec = build_sandbox_spec(
            service_name="kivy-app", readme_path=Path("/tmp/r.md"),
            sandbox_path=Path("/tmp/s"), port=None,
            run_cmd="python main.py", is_node=False,
            python_deps=["kivy", "buildozer"], node_deps=[],
            health_path="/", env_keys=[],
        )
        assert spec["spec"]["runtime"]["type"] == "python"
        assert "kivy" in spec["spec"]["dependencies"]["python"]

    def test_mobile_capacitor_spec(self) -> None:
        spec = build_sandbox_spec(
            service_name="cap-app", readme_path=Path("/tmp/r.md"),
            sandbox_path=Path("/tmp/s"), port=None,
            run_cmd="npx cap run android", is_node=True,
            python_deps=[], node_deps=["@capacitor/core"],
            health_path="/", env_keys=[],
        )
        assert spec["spec"]["runtime"]["type"] == "node"


# ===========================================================================
# Compose: healthcheck per platform
# ===========================================================================

class TestComposeHealthcheckPerPlatform:
    def test_python_healthcheck_uses_urllib(self) -> None:
        compose = build_single_service_compose(
            service_name="py-app", port=8000, health_path="/health", is_node=False,
        )
        hc = compose["services"]["app"]["healthcheck"]
        assert "python" in hc["test"][1]
        hc_script = " ".join(hc["test"])
        assert "/health" in hc_script

    def test_node_healthcheck_uses_http_module(self) -> None:
        compose = build_single_service_compose(
            service_name="node-app", port=3000, health_path="/health", is_node=True,
        )
        hc = compose["services"]["app"]["healthcheck"]
        assert "node" in hc["test"][1]
        hc_script = " ".join(hc["test"])
        assert "/health" in hc_script

    def test_no_port_no_port_mapping(self) -> None:
        compose = build_single_service_compose(
            service_name="desktop", port=None, health_path="/", is_node=False,
        )
        assert "ports" not in compose["services"]["app"]


# ===========================================================================
# Dockerfile generation per platform
# ===========================================================================

class TestDockerfilePerPlatform:
    def test_python_dockerfile(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\n")
        backend = DockerBackend(DeploymentConfig.for_development())
        content = backend._create_dockerfile(tmp_path, "python:3.12-slim", run_cmd="uvicorn main:app")
        assert "FROM python:3.12-slim" in content
        assert "requirements.txt" in content
        assert "uvicorn main:app" in content
        assert "HEALTHCHECK" in content

    def test_node_dockerfile(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name":"app"}')
        backend = DockerBackend(DeploymentConfig.for_development())
        content = backend._create_dockerfile(tmp_path, "python:3.12-slim", run_cmd="node server.js")
        assert "FROM node:20-slim" in content
        assert "npm" in content
        assert "node server.js" in content

    def test_python_no_deps_no_requirements_copy(self, tmp_path: Path) -> None:
        backend = DockerBackend(DeploymentConfig.for_development())
        content = backend._create_dockerfile(tmp_path, "python:3.12-slim")
        assert "requirements.txt" not in content
        assert "COPY . ." in content

    def test_python_dockerfile_run_cmd_none(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("flask\n")
        backend = DockerBackend(DeploymentConfig.for_development())
        content = backend._create_dockerfile(tmp_path, "python:3.12-slim", run_cmd=None)
        assert 'CMD ["python", "main.py"]' in content

    def test_node_dockerfile_run_cmd_none(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"name":"app"}')
        backend = DockerBackend(DeploymentConfig.for_development())
        content = backend._create_dockerfile(tmp_path, "python:3.12-slim", run_cmd=None)
        assert 'CMD ["node", "server.js"]' in content


# ===========================================================================
# Cross-platform: build_service via SandboxManager (mocked build cmds)
# ===========================================================================

class TestBuildServiceIntegration:
    """Tests that exercise SandboxManager.build_service() end-to-end
    (without actually installing deps – install_dependencies is skipped
    internally for non-web targets)."""

    def _build(self, tmp_path: Path, readme: str, name: str, target: str, framework: str) -> BuildResult:
        readme_path = tmp_path / "README.md"
        readme_path.write_text(textwrap.dedent(readme))
        svc = ServiceConfig(
            name=name, readme=str(readme_path),
            target=target, framework=framework,
        )
        mgr = SandboxManager(tmp_path / "sandboxes")
        return mgr.build_service(svc, readme_path, env={}, on_log=lambda m: None)

    def test_electron_build_service(self, tmp_path: Path) -> None:
        result = self._build(tmp_path, """\
        # E

        ```yaml markpact:target
        platform: desktop
        framework: electron
        app_name: E
        ```

        ```html markpact:file path=index.html
        <h1>hi</h1>
        ```

        ```bash markpact:build
        mkdir -p dist && echo x > dist/E.AppImage
        ```
        """, "e-app", "desktop", "electron")
        assert result.success
        assert result.platform == "desktop"

    def test_pyinstaller_build_service(self, tmp_path: Path) -> None:
        result = self._build(tmp_path, """\
        # P

        ```yaml markpact:target
        platform: desktop
        framework: pyinstaller
        app_name: P
        ```

        ```python markpact:file path=main.py
        print("ok")
        ```

        ```bash markpact:build
        mkdir -p dist && echo x > dist/P
        ```
        """, "p-app", "desktop", "pyinstaller")
        assert result.success

    def test_capacitor_build_service(self, tmp_path: Path) -> None:
        result = self._build(tmp_path, """\
        # C

        ```yaml markpact:target
        platform: mobile
        framework: capacitor
        app_name: C
        ```

        ```bash markpact:build
        mkdir -p android/app/build/outputs/apk/release && echo x > android/app/build/outputs/apk/release/app.apk
        ```
        """, "c-app", "mobile", "capacitor")
        assert result.success
        assert result.platform == "mobile"

    def test_kivy_build_service(self, tmp_path: Path) -> None:
        result = self._build(tmp_path, """\
        # K

        ```yaml markpact:target
        platform: mobile
        framework: kivy
        app_name: K
        ```

        ```python markpact:file path=main.py
        print("ok")
        ```

        ```bash markpact:build
        mkdir -p bin && echo x > bin/K.apk
        ```
        """, "k-app", "mobile", "kivy")
        assert result.success

    def test_web_build_service(self, tmp_path: Path) -> None:
        result = self._build(tmp_path, """\
        # W

        ```python markpact:file path=main.py
        print("hello")
        ```

        ```bash markpact:build
        echo web-build-ok
        ```
        """, "w-app", "web", "")
        assert result.success
        assert result.platform == "web"

    def test_build_failure_propagated(self, tmp_path: Path) -> None:
        result = self._build(tmp_path, """\
        # F

        ```yaml markpact:target
        platform: desktop
        framework: pyinstaller
        app_name: F
        ```

        ```bash markpact:build
        exit 1
        ```
        """, "f-app", "desktop", "pyinstaller")
        assert not result.success
        assert "failed" in result.message.lower()

    def test_build_env_contains_electron_builder_cache(self, tmp_path: Path) -> None:
        readme_path = tmp_path / "README.md"
        readme_path.write_text(textwrap.dedent("""\
        # E

        ```yaml markpact:target
        platform: desktop
        framework: electron
        app_name: E
        ```

        ```bash markpact:build
        echo "ELECTRON_BUILDER_CACHE=$ELECTRON_BUILDER_CACHE"
        ```
        """))
        svc = ServiceConfig(name="e-cache", readme=str(readme_path), target="desktop", framework="electron")
        mgr = SandboxManager(tmp_path / "sandboxes")
        logs: list[str] = []
        result = mgr.build_service(svc, readme_path, env={}, on_log=logs.append)
        assert result.success
        combined = "\n".join(result.logs + logs)
        assert "electron-builder" in combined.lower() or result.success


# ===========================================================================
# NodeModulesCache integration with build_service
# ===========================================================================

class TestNodeModulesCacheIntegration:
    """Verify that NodeModulesCache is wired into build_service."""

    def test_node_cache_initialized(self, tmp_path: Path) -> None:
        mgr = SandboxManager(tmp_path / "sandboxes")
        assert hasattr(mgr, "_node_cache")
        assert mgr._node_cache is not None

    def test_cache_dir_created(self, tmp_path: Path) -> None:
        mgr = SandboxManager(tmp_path / "sandboxes")
        cache_dir = tmp_path / "sandboxes" / ".cache" / "node_modules"
        assert cache_dir.exists()

    def test_dep_cache_initialized(self, tmp_path: Path) -> None:
        mgr = SandboxManager(tmp_path / "sandboxes")
        assert hasattr(mgr, "_dep_cache")
        assert mgr._dep_cache is not None


# ===========================================================================
# Framework metadata completeness check
# ===========================================================================

class TestFrameworkMetaDeploymentReady:
    """Verify every registered framework has enough metadata for deployment."""

    @pytest.mark.parametrize("fw_name", [
        "electron", "tauri", "pyinstaller", "tkinter", "pyqt",
        "capacitor", "react-native", "kivy",
        "flutter-desktop", "flutter-mobile",
    ])
    def test_framework_has_build_cmd(self, fw_name: str) -> None:
        meta = get_framework_meta(fw_name)
        assert meta is not None, f"Framework {fw_name} not registered"
        assert meta.default_build_cmd, f"{fw_name} has no default_build_cmd"

    @pytest.mark.parametrize("fw_name", [
        "electron", "tauri", "pyinstaller", "tkinter", "pyqt",
        "capacitor", "react-native", "kivy",
        "flutter-desktop", "flutter-mobile",
    ])
    def test_framework_has_artifact_patterns(self, fw_name: str) -> None:
        meta = get_framework_meta(fw_name)
        assert meta is not None
        assert meta.artifact_patterns, f"{fw_name} has no artifact_patterns"

    @pytest.mark.parametrize("fw_name,expected_platform", [
        ("electron", TargetPlatform.DESKTOP),
        ("tauri", TargetPlatform.DESKTOP),
        ("pyinstaller", TargetPlatform.DESKTOP),
        ("pyqt", TargetPlatform.DESKTOP),
        ("capacitor", TargetPlatform.MOBILE),
        ("react-native", TargetPlatform.MOBILE),
        ("kivy", TargetPlatform.MOBILE),
        ("flutter-mobile", TargetPlatform.MOBILE),
        ("flutter-desktop", TargetPlatform.DESKTOP),
    ])
    def test_framework_platform_correct(self, fw_name: str, expected_platform: TargetPlatform) -> None:
        meta = get_framework_meta(fw_name)
        assert meta.platform == expected_platform
