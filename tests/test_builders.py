"""Tests for pactown.builders module."""

import json
from pathlib import Path

from pactown.builders import (
    BuildResult,
    DesktopBuilder,
    MobileBuilder,
    WebBuilder,
    get_builder,
    get_builder_for_target,
)
from pactown.targets import TargetConfig, TargetPlatform


# ---------------------------------------------------------------------------
# Builder registry
# ---------------------------------------------------------------------------

def test_get_builder_web() -> None:
    b = get_builder(TargetPlatform.WEB)
    assert isinstance(b, WebBuilder)
    assert b.platform_name == "web"


def test_get_builder_desktop() -> None:
    b = get_builder(TargetPlatform.DESKTOP)
    assert isinstance(b, DesktopBuilder)
    assert b.platform_name == "desktop"


def test_get_builder_mobile() -> None:
    b = get_builder(TargetPlatform.MOBILE)
    assert isinstance(b, MobileBuilder)
    assert b.platform_name == "mobile"


def test_get_builder_for_target_none_defaults_to_web() -> None:
    b = get_builder_for_target(None)
    assert isinstance(b, WebBuilder)


def test_get_builder_for_target_desktop() -> None:
    cfg = TargetConfig(platform=TargetPlatform.DESKTOP, framework="electron")
    b = get_builder_for_target(cfg)
    assert isinstance(b, DesktopBuilder)


# ---------------------------------------------------------------------------
# DesktopBuilder.scaffold - Electron
# ---------------------------------------------------------------------------

def test_desktop_scaffold_electron(tmp_path: Path) -> None:
    builder = DesktopBuilder()
    builder.scaffold(
        tmp_path,
        framework="electron",
        app_name="test-app",
        extra={"window_width": 800, "window_height": 600, "app_id": "com.test.app"},
    )

    # Should create package.json and main.js
    pkg_json = tmp_path / "package.json"
    assert pkg_json.exists()
    pkg = json.loads(pkg_json.read_text())
    assert pkg["name"] == "test-app"
    assert "electron" in pkg["scripts"].get("start", "")

    main_js = tmp_path / "main.js"
    assert main_js.exists()
    content = main_js.read_text()
    assert "800" in content
    assert "600" in content


def test_desktop_scaffold_electron_existing_package_json(tmp_path: Path) -> None:
    """Scaffold should merge Electron fields into existing package.json."""
    pkg_json = tmp_path / "package.json"
    pkg_json.write_text('{"name": "existing", "version": "1.0.0", "private": true}')

    builder = DesktopBuilder()
    builder.scaffold(tmp_path, framework="electron", app_name="test-app")

    pkg = json.loads(pkg_json.read_text())
    assert pkg["name"] == "existing"  # preserved
    assert pkg["main"] == "main.js"  # added
    assert "electron" in pkg["scripts"].get("start", "")  # added
    assert "build" in pkg  # added


# ---------------------------------------------------------------------------
# DesktopBuilder.scaffold - Tauri
# ---------------------------------------------------------------------------

def test_desktop_scaffold_tauri(tmp_path: Path) -> None:
    builder = DesktopBuilder()
    builder.scaffold(
        tmp_path,
        framework="tauri",
        app_name="tauri-app",
        extra={"app_id": "com.test.tauri"},
    )

    conf = tmp_path / "src-tauri" / "tauri.conf.json"
    assert conf.exists()
    data = json.loads(conf.read_text())
    assert data["package"]["productName"] == "tauri-app"


# ---------------------------------------------------------------------------
# DesktopBuilder.scaffold - PyInstaller
# ---------------------------------------------------------------------------

def test_desktop_scaffold_pyinstaller(tmp_path: Path) -> None:
    builder = DesktopBuilder()
    builder.scaffold(tmp_path, framework="pyinstaller", app_name="myapp")

    spec = tmp_path / "myapp.spec"
    assert spec.exists()
    assert "myapp" in spec.read_text()


# ---------------------------------------------------------------------------
# MobileBuilder.scaffold - Capacitor
# ---------------------------------------------------------------------------

def test_mobile_scaffold_capacitor(tmp_path: Path) -> None:
    builder = MobileBuilder()
    builder.scaffold(
        tmp_path,
        framework="capacitor",
        app_name="cap-app",
        extra={"app_id": "com.test.cap"},
    )

    cap_cfg = tmp_path / "capacitor.config.json"
    assert cap_cfg.exists()
    data = json.loads(cap_cfg.read_text())
    assert data["appName"] == "cap-app"
    assert data["appId"] == "com.test.cap"

    pkg_json = tmp_path / "package.json"
    assert pkg_json.exists()
    pkg = json.loads(pkg_json.read_text())
    assert "cap:sync" in pkg.get("scripts", {})


# ---------------------------------------------------------------------------
# MobileBuilder.scaffold - Kivy
# ---------------------------------------------------------------------------

def test_mobile_scaffold_kivy(tmp_path: Path) -> None:
    builder = MobileBuilder()
    builder.scaffold(
        tmp_path,
        framework="kivy",
        app_name="kivyapp",
        extra={"app_id": "com.test.kivy", "fullscreen": True},
    )

    spec = tmp_path / "buildozer.spec"
    assert spec.exists()
    text = spec.read_text()
    assert "kivyapp" in text
    assert "fullscreen = 1" in text


# ---------------------------------------------------------------------------
# WebBuilder (no-op scaffolding, simple build)
# ---------------------------------------------------------------------------

def test_web_builder_scaffold_noop(tmp_path: Path) -> None:
    builder = WebBuilder()
    # Should not raise
    builder.scaffold(tmp_path, framework="fastapi")


def test_web_builder_build_no_cmd(tmp_path: Path) -> None:
    builder = WebBuilder()
    result = builder.build(tmp_path)
    assert result.success
    assert result.platform == "web"


# ---------------------------------------------------------------------------
# BuildResult dataclass
# ---------------------------------------------------------------------------

def test_build_result_defaults() -> None:
    r = BuildResult(success=True, platform="desktop")
    assert r.success
    assert r.artifacts == []
    assert r.output_dir is None
    assert r.elapsed_seconds == 0.0
