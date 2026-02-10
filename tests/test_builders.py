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


def test_desktop_scaffold_electron_merges_main_into_minimal_package_json(tmp_path: Path) -> None:
    """Regression: _ensure_package_json writes minimal package.json without 'main'.

    Scaffold must add 'main' so Electron can find the entry point.
    This is the exact scenario that caused the 'Cannot find module' crash.
    """
    pkg_json = tmp_path / "package.json"
    # Simulate what SandboxManager._ensure_package_json writes
    pkg_json.write_text(json.dumps({
        "name": "service-54-tom-sapletta-com",
        "version": "1.0.0",
        "private": True,
        "dependencies": {"electron": "latest"},
    }, indent=2))

    builder = DesktopBuilder()
    builder.scaffold(tmp_path, framework="electron", app_name="my-electron-app")

    pkg = json.loads(pkg_json.read_text())
    assert pkg["main"] == "main.js"
    assert pkg["name"] == "service-54-tom-sapletta-com"  # not overwritten
    assert "electron" not in pkg.get("dependencies", {}), "electron must be moved to devDependencies"
    assert "electron" in pkg.get("devDependencies", {}), "electron must be in devDependencies"
    assert pkg["devDependencies"]["electron"] == "latest"  # version preserved

    # main.js should also be created
    assert (tmp_path / "main.js").exists()


def test_desktop_scaffold_electron_does_not_overwrite_existing_main(tmp_path: Path) -> None:
    """If package.json already has 'main', scaffold must not overwrite it."""
    pkg_json = tmp_path / "package.json"
    pkg_json.write_text(json.dumps({
        "name": "custom-app",
        "main": "custom-entry.js",
        "scripts": {"start": "electron ."},
        "build": {"appId": "com.custom.app"},
    }, indent=2))

    builder = DesktopBuilder()
    builder.scaffold(tmp_path, framework="electron", app_name="custom-app")

    pkg = json.loads(pkg_json.read_text())
    assert pkg["main"] == "custom-entry.js"  # not overwritten
    assert pkg["scripts"]["start"] == "electron ."  # not overwritten


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

# ---------------------------------------------------------------------------
# _patch_electron_no_sandbox
# ---------------------------------------------------------------------------

def test_patch_no_sandbox_user_provided_main_js(tmp_path: Path) -> None:
    """User-provided main.js without --no-sandbox must be patched."""
    main_js = tmp_path / "main.js"
    main_js.write_text(
        "const { app, BrowserWindow } = require('electron');\n"
        "app.whenReady().then(() => {});\n"
    )
    patched = DesktopBuilder._patch_electron_no_sandbox(tmp_path)
    assert patched is True
    content = main_js.read_text()
    assert "app.commandLine.appendSwitch('no-sandbox')" in content
    assert "require('electron')" in content


def test_patch_no_sandbox_already_patched(tmp_path: Path) -> None:
    """If main.js already has --no-sandbox, do not patch again."""
    main_js = tmp_path / "main.js"
    main_js.write_text(
        "const { app } = require('electron');\n"
        "app.commandLine.appendSwitch('no-sandbox');\n"
        "app.whenReady().then(() => {});\n"
    )
    patched = DesktopBuilder._patch_electron_no_sandbox(tmp_path)
    assert patched is False


def test_patch_no_sandbox_scaffolded_default(tmp_path: Path) -> None:
    """Scaffolded default main.js already contains --no-sandbox."""
    builder = DesktopBuilder()
    builder.scaffold(tmp_path, framework="electron", app_name="test")
    content = (tmp_path / "main.js").read_text()
    assert "no-sandbox" in content
    # Patching again should be a no-op
    assert DesktopBuilder._patch_electron_no_sandbox(tmp_path) is False


def test_patch_no_sandbox_desktop_notes_main_js(tmp_path: Path) -> None:
    """Exact main.js from Desktop Notes example must be patched correctly."""
    main_js = tmp_path / "main.js"
    main_js.write_text(
        "const { app, BrowserWindow, ipcMain } = require('electron');\n"
        "const path = require('path');\n"
        "const fs = require('fs');\n"
        "\n"
        "const NOTES_FILE = path.join(app.getPath('userData'), 'notes.json');\n"
        "\n"
        "app.whenReady().then(createWindow);\n"
    )
    patched = DesktopBuilder._patch_electron_no_sandbox(tmp_path)
    assert patched is True
    content = main_js.read_text()
    assert "app.commandLine.appendSwitch('no-sandbox')" in content
    # Must appear before app.whenReady
    sandbox_pos = content.index("no-sandbox")
    ready_pos = content.index("app.whenReady")
    assert sandbox_pos < ready_pos


def test_patch_no_sandbox_no_main_js(tmp_path: Path) -> None:
    """No main.js → no patch."""
    assert DesktopBuilder._patch_electron_no_sandbox(tmp_path) is False


def test_patch_no_sandbox_double_quotes(tmp_path: Path) -> None:
    """main.js using double quotes for require."""
    main_js = tmp_path / "main.js"
    main_js.write_text(
        'const { app } = require("electron");\n'
        'app.whenReady().then(() => {});\n'
    )
    assert DesktopBuilder._patch_electron_no_sandbox(tmp_path) is True
    assert "no-sandbox" in main_js.read_text()


def test_patch_no_sandbox_es_module_single_quotes(tmp_path: Path) -> None:
    """ES module import with single quotes must be patched."""
    main_js = tmp_path / "main.js"
    main_js.write_text(
        "import { app, BrowserWindow } from 'electron';\n"
        "app.whenReady().then(() => {});\n"
    )
    assert DesktopBuilder._patch_electron_no_sandbox(tmp_path) is True
    content = main_js.read_text()
    assert "app.commandLine.appendSwitch('no-sandbox')" in content
    sandbox_pos = content.index("no-sandbox")
    ready_pos = content.index("app.whenReady")
    assert sandbox_pos < ready_pos


def test_patch_no_sandbox_es_module_double_quotes(tmp_path: Path) -> None:
    """ES module import with double quotes must be patched."""
    main_js = tmp_path / "main.js"
    main_js.write_text(
        'import { app, BrowserWindow } from "electron";\n'
        "app.whenReady().then(() => {});\n"
    )
    assert DesktopBuilder._patch_electron_no_sandbox(tmp_path) is True
    content = main_js.read_text()
    assert "no-sandbox" in content


def test_patch_no_sandbox_ultimate_fallback(tmp_path: Path) -> None:
    """main.js with no recognizable pattern gets no-sandbox prepended at top."""
    main_js = tmp_path / "main.js"
    main_js.write_text(
        "// custom electron launcher\n"
        "doSomething();\n"
    )
    assert DesktopBuilder._patch_electron_no_sandbox(tmp_path) is True
    content = main_js.read_text()
    assert "no-sandbox" in content
    # Must be at the beginning
    assert content.startswith("// AppImage on Linux requires --no-sandbox")


def test_generate_linux_launcher_creates_files(tmp_path: Path) -> None:
    """_generate_linux_launcher creates run.sh + README.txt next to AppImage."""
    dist = tmp_path / "dist"
    dist.mkdir()
    appimage = dist / "myapp-1.0.0.AppImage"
    appimage.write_bytes(b"fake")

    DesktopBuilder._generate_linux_launcher(tmp_path)

    run_sh = dist / "run.sh"
    readme = dist / "README.txt"
    assert run_sh.exists()
    assert readme.exists()

    run_content = run_sh.read_text()
    assert "myapp-1.0.0.AppImage" in run_content
    assert "--no-sandbox" in run_content
    assert "#!/bin/bash" in run_content
    # Must be executable
    import os
    assert os.access(str(run_sh), os.X_OK)

    readme_content = readme.read_text()
    assert "myapp-1.0.0.AppImage" in readme_content
    assert "chmod +x run.sh" in readme_content
    assert "--no-sandbox" in readme_content
    assert "libfuse2" in readme_content


def test_generate_linux_launcher_no_dist(tmp_path: Path) -> None:
    """No dist/ directory → no files generated."""
    DesktopBuilder._generate_linux_launcher(tmp_path)
    assert not (tmp_path / "dist" / "run.sh").exists()


def test_generate_linux_launcher_no_appimage(tmp_path: Path) -> None:
    """dist/ exists but no AppImage → no files generated."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "app.exe").write_bytes(b"fake")
    DesktopBuilder._generate_linux_launcher(tmp_path)
    assert not (dist / "run.sh").exists()


def test_build_result_defaults() -> None:
    r = BuildResult(success=True, platform="desktop")
    assert r.success
    assert r.artifacts == []
    assert r.output_dir is None
    assert r.elapsed_seconds == 0.0
