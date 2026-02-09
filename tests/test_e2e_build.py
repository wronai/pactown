"""End-to-end tests for the desktop/mobile build pipeline.

These tests exercise the full flow: parse markpact README → create sandbox →
scaffold → build (using a dummy build command) → verify BuildResult.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Optional

import pytest

from pactown.builders import BuildResult, DesktopBuilder, MobileBuilder, WebBuilder, get_builder_for_target
from pactown.config import ServiceConfig
from pactown.markpact_blocks import parse_blocks, extract_target_config, extract_build_cmd
from pactown.targets import TargetConfig, TargetPlatform


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


# ---------------------------------------------------------------------------
# E2E: Desktop Electron (scaffold + dummy build)
# ---------------------------------------------------------------------------

class TestE2EDesktopElectron:
    """Full pipeline for an Electron desktop app."""

    MARKPACT = """\
    # Calculator

    ```yaml markpact:target
    platform: desktop
    framework: electron
    app_name: Calculator
    app_id: com.test.calc
    window_width: 800
    window_height: 600
    ```

    ```html markpact:file path=index.html
    <h1>Calculator</h1>
    ```

    ```javascript markpact:deps
    electron
    ```

    ```bash markpact:build
    echo "build-ok" > dist/calculator.AppImage
    ```

    ```bash markpact:run
    npx electron .
    ```
    """

    def test_parse_all_blocks(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        blocks, target_cfg, build_cmd = _parse_and_resolve(readme)

        assert len(blocks) == 5
        assert target_cfg is not None
        assert target_cfg.platform == TargetPlatform.DESKTOP
        assert target_cfg.framework == "electron"
        assert target_cfg.app_name == "Calculator"
        assert target_cfg.app_id == "com.test.calc"
        assert build_cmd is not None
        assert "echo" in build_cmd

    def test_scaffold_creates_package_json(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        _, target_cfg, _ = _parse_and_resolve(readme)

        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        builder = DesktopBuilder()
        builder.scaffold(
            sandbox,
            framework=target_cfg.framework,
            app_name=target_cfg.app_name,
            extra={
                "app_id": target_cfg.app_id,
                "window_width": target_cfg.window_width,
                "window_height": target_cfg.window_height,
            },
        )

        pkg = sandbox / "package.json"
        assert pkg.exists()
        data = json.loads(pkg.read_text())
        assert data["name"] == "Calculator"
        assert data["build"]["appId"] == "com.test.calc"

        main_js = sandbox / "main.js"
        assert main_js.exists()
        assert "800" in main_js.read_text()  # window_width

    def test_full_build_with_dummy_cmd(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        _, target_cfg, build_cmd = _parse_and_resolve(readme)

        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        (sandbox / "dist").mkdir()

        builder = DesktopBuilder()
        builder.scaffold(
            sandbox,
            framework=target_cfg.framework,
            app_name=target_cfg.app_name,
            extra={"app_id": target_cfg.app_id},
        )

        result = builder.build(
            sandbox,
            build_cmd=build_cmd,
            framework=target_cfg.framework,
            targets=target_cfg.effective_build_targets(),
        )

        assert result.success
        assert result.platform == "desktop"
        assert result.framework == "electron"
        assert result.elapsed_seconds >= 0
        assert (sandbox / "dist" / "calculator.AppImage").exists()
        assert len(result.artifacts) >= 1

    def test_builder_registry_resolves_desktop(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        _, target_cfg, _ = _parse_and_resolve(readme)

        builder = get_builder_for_target(target_cfg)
        assert isinstance(builder, DesktopBuilder)


# ---------------------------------------------------------------------------
# E2E: Desktop PyInstaller
# ---------------------------------------------------------------------------

class TestE2EDesktopPyInstaller:
    MARKPACT = """\
    # MyApp

    ```yaml markpact:target
    platform: desktop
    framework: pyinstaller
    app_name: myapp
    ```

    ```python markpact:file path=main.py
    print("hello world")
    ```

    ```python markpact:deps
    pyinstaller
    ```

    ```bash markpact:build
    mkdir -p dist && echo "binary" > dist/myapp
    ```

    ```bash markpact:run
    python main.py
    ```
    """

    def test_full_pipeline(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        blocks, target_cfg, build_cmd = _parse_and_resolve(readme)

        assert target_cfg.platform == TargetPlatform.DESKTOP
        assert target_cfg.framework == "pyinstaller"

        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        builder = DesktopBuilder()
        builder.scaffold(sandbox, framework="pyinstaller", app_name="myapp")

        # Verify spec file created
        assert (sandbox / "myapp.spec").exists()

        result = builder.build(
            sandbox, build_cmd=build_cmd, framework="pyinstaller"
        )

        assert result.success
        assert (sandbox / "dist" / "myapp").exists()
        assert len(result.artifacts) >= 1


# ---------------------------------------------------------------------------
# E2E: Desktop Tauri
# ---------------------------------------------------------------------------

class TestE2EDesktopTauri:
    MARKPACT = """\
    # TauriApp

    ```yaml markpact:target
    platform: desktop
    framework: tauri
    app_name: TauriApp
    app_id: com.test.tauri
    targets:
      - linux
      - windows
    ```

    ```html markpact:file path=index.html
    <h1>Tauri</h1>
    ```

    ```bash markpact:build
    echo "tauri build done"
    ```
    """

    def test_scaffold_and_parse(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        _, target_cfg, build_cmd = _parse_and_resolve(readme)

        assert target_cfg.platform == TargetPlatform.DESKTOP
        assert target_cfg.framework == "tauri"
        assert target_cfg.targets == ["linux", "windows"]

        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        builder = DesktopBuilder()
        builder.scaffold(
            sandbox,
            framework="tauri",
            app_name="TauriApp",
            extra={"app_id": "com.test.tauri"},
        )

        conf = sandbox / "src-tauri" / "tauri.conf.json"
        assert conf.exists()
        data = json.loads(conf.read_text())
        assert data["package"]["productName"] == "TauriApp"
        assert data["tauri"]["bundle"]["identifier"] == "com.test.tauri"


# ---------------------------------------------------------------------------
# E2E: Mobile Capacitor
# ---------------------------------------------------------------------------

class TestE2EMobileCapacitor:
    MARKPACT = """\
    # TodoApp

    ```yaml markpact:target
    platform: mobile
    framework: capacitor
    app_name: TodoApp
    app_id: com.test.todo
    targets:
      - android
      - ios
    ```

    ```html markpact:file path=dist/index.html
    <h1>Todo</h1>
    ```

    ```javascript markpact:deps
    @capacitor/core
    @capacitor/cli
    ```

    ```bash markpact:build
    mkdir -p android/app/build/outputs/apk/release && echo "apk" > android/app/build/outputs/apk/release/app.apk
    ```

    ```bash markpact:run
    npx cap run android
    ```
    """

    def test_full_pipeline(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        blocks, target_cfg, build_cmd = _parse_and_resolve(readme)

        assert target_cfg.platform == TargetPlatform.MOBILE
        assert target_cfg.framework == "capacitor"
        assert target_cfg.targets == ["android", "ios"]
        assert target_cfg.app_id == "com.test.todo"

        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        builder = MobileBuilder()
        builder.scaffold(
            sandbox,
            framework="capacitor",
            app_name="TodoApp",
            extra={"app_id": "com.test.todo"},
        )

        # Verify capacitor config
        cap_cfg = sandbox / "capacitor.config.json"
        assert cap_cfg.exists()
        data = json.loads(cap_cfg.read_text())
        assert data["appName"] == "TodoApp"
        assert data["appId"] == "com.test.todo"

        # Verify package.json scripts
        pkg = sandbox / "package.json"
        assert pkg.exists()
        pkg_data = json.loads(pkg.read_text())
        assert "cap:sync" in pkg_data["scripts"]

        # Build with dummy command
        result = builder.build(
            sandbox,
            build_cmd=build_cmd,
            framework="capacitor",
            targets=["android", "ios"],
        )

        assert result.success
        assert result.platform == "mobile"
        apk = sandbox / "android" / "app" / "build" / "outputs" / "apk" / "release" / "app.apk"
        assert apk.exists()
        assert len(result.artifacts) >= 1


# ---------------------------------------------------------------------------
# E2E: Mobile Kivy
# ---------------------------------------------------------------------------

class TestE2EMobileKivy:
    MARKPACT = """\
    # WeatherApp

    ```yaml markpact:target
    platform: mobile
    framework: kivy
    app_name: WeatherApp
    app_id: com.test.weather
    targets:
      - android
    fullscreen: true
    ```

    ```python markpact:file path=main.py
    from kivy.app import App
    class WeatherApp(App):
        pass
    ```

    ```python markpact:deps
    kivy
    buildozer
    ```

    ```bash markpact:build
    mkdir -p bin && echo "apk" > bin/weather.apk
    ```
    """

    def test_full_pipeline(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        _, target_cfg, build_cmd = _parse_and_resolve(readme)

        assert target_cfg.platform == TargetPlatform.MOBILE
        assert target_cfg.framework == "kivy"
        assert target_cfg.fullscreen is True

        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()

        builder = MobileBuilder()
        builder.scaffold(
            sandbox,
            framework="kivy",
            app_name="WeatherApp",
            extra={
                "app_id": "com.test.weather",
                "fullscreen": True,
            },
        )

        # Verify buildozer.spec
        spec = sandbox / "buildozer.spec"
        assert spec.exists()
        text = spec.read_text()
        assert "WeatherApp" in text
        assert "fullscreen = 1" in text

        result = builder.build(
            sandbox,
            build_cmd=build_cmd,
            framework="kivy",
            targets=["android"],
        )

        assert result.success
        assert (sandbox / "bin" / "weather.apk").exists()
        assert len(result.artifacts) >= 1


# ---------------------------------------------------------------------------
# E2E: Web builder (existing behavior, regression)
# ---------------------------------------------------------------------------

class TestE2EWebBuilder:
    MARKPACT = """\
    # API Service

    ```python markpact:file path=main.py
    from fastapi import FastAPI
    app = FastAPI()

    @app.get("/")
    def root():
        return {"status": "ok"}
    ```

    ```python markpact:deps
    fastapi
    uvicorn
    ```

    ```bash markpact:run
    uvicorn main:app --host 0.0.0.0 --port $PORT
    ```
    """

    def test_web_no_target_block_defaults_to_web(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, self.MARKPACT)
        _, target_cfg, build_cmd = _parse_and_resolve(readme)

        # No markpact:target block → None
        assert target_cfg is None
        assert build_cmd is None

        builder = get_builder_for_target(None)
        assert isinstance(builder, WebBuilder)

    def test_web_build_succeeds_without_cmd(self, tmp_path: Path) -> None:
        builder = WebBuilder()
        result = builder.build(tmp_path)
        assert result.success
        assert result.platform == "web"

    def test_web_build_with_optional_step(self, tmp_path: Path) -> None:
        (tmp_path / "built.txt").unlink(missing_ok=True)

        builder = WebBuilder()
        result = builder.build(
            tmp_path,
            build_cmd="echo ok > built.txt",
        )

        assert result.success
        assert (tmp_path / "built.txt").exists()


# ---------------------------------------------------------------------------
# E2E: ServiceConfig round-trip with target fields
# ---------------------------------------------------------------------------

class TestE2EServiceConfigTargets:
    def test_service_config_from_dict_with_target(self) -> None:
        cfg = ServiceConfig.from_dict("myapp", {
            "readme": "myapp/README.md",
            "port": 8000,
            "target": "desktop",
            "framework": "electron",
            "build_targets": ["linux", "windows"],
            "build_cmd": "npx electron-builder",
        })

        assert cfg.target == "desktop"
        assert cfg.framework == "electron"
        assert cfg.build_targets == ["linux", "windows"]
        assert cfg.build_cmd == "npx electron-builder"

    def test_service_config_defaults_to_web(self) -> None:
        cfg = ServiceConfig.from_dict("svc", {"readme": "svc/README.md"})
        assert cfg.target == "web"
        assert cfg.framework is None
        assert cfg.build_targets == []
        assert cfg.build_cmd is None

    def test_service_config_build_targets_as_csv_string(self) -> None:
        cfg = ServiceConfig.from_dict("svc", {
            "readme": "svc/README.md",
            "build_targets": "android, ios",
        })
        assert cfg.build_targets == ["android", "ios"]


# ---------------------------------------------------------------------------
# E2E: Cross-platform build from single README
# ---------------------------------------------------------------------------

class TestE2ECrossPlatformScenario:
    """Verify that the same builder infrastructure supports switching targets."""

    DESKTOP_MARKPACT = """\
    # App

    ```yaml markpact:target
    platform: desktop
    framework: electron
    app_name: CrossApp
    ```

    ```bash markpact:build
    echo done
    ```
    """

    MOBILE_MARKPACT = """\
    # App

    ```yaml markpact:target
    platform: mobile
    framework: capacitor
    app_name: CrossApp
    targets:
      - android
    ```

    ```bash markpact:build
    echo done
    ```
    """

    def test_same_app_different_platforms(self, tmp_path: Path) -> None:
        # Desktop variant
        (tmp_path / "desktop").mkdir(parents=True, exist_ok=True)
        d_readme = _write_readme(tmp_path / "desktop", self.DESKTOP_MARKPACT)
        _, d_cfg, _ = _parse_and_resolve(d_readme)
        assert d_cfg.platform == TargetPlatform.DESKTOP

        d_builder = get_builder_for_target(d_cfg)
        assert isinstance(d_builder, DesktopBuilder)

        # Mobile variant
        m_dir = tmp_path / "mobile"
        m_dir.mkdir(parents=True, exist_ok=True)
        m_readme = _write_readme(m_dir, self.MOBILE_MARKPACT)
        _, m_cfg, _ = _parse_and_resolve(m_readme)
        assert m_cfg.platform == TargetPlatform.MOBILE

        m_builder = get_builder_for_target(m_cfg)
        assert isinstance(m_builder, MobileBuilder)

    def test_build_failure_returns_failed_result(self, tmp_path: Path) -> None:
        builder = DesktopBuilder()
        result = builder.build(
            tmp_path,
            build_cmd="false",  # unix 'false' exits with 1
            framework="electron",
        )

        assert not result.success
        assert result.platform == "desktop"
        assert "failed" in result.message.lower()
