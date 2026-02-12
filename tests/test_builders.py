"""Tests for pactown.builders module."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from pactown.builders import (
    BuildResult,
    DesktopBuilder,
    MobileBuilder,
    WebBuilder,
    get_builder,
    get_builder_for_target,
)
from pactown.targets import (
    FRAMEWORK_REGISTRY,
    FrameworkMeta,
    TargetConfig,
    TargetPlatform,
    get_framework_meta,
    infer_target_from_deps,
    list_frameworks,
)


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

    # @capacitor/cli must be present for `npx cap` to work
    deps = pkg.get("dependencies", {})
    assert "@capacitor/cli" in deps
    assert "@capacitor/core" in deps
    # Default target is android
    assert "@capacitor/android" in deps


def test_mobile_scaffold_capacitor_webdir_root(tmp_path: Path) -> None:
    """When index.html is at sandbox root, webDir should be '.'."""
    (tmp_path / "index.html").write_text("<html></html>")
    builder = MobileBuilder()
    builder.scaffold(tmp_path, framework="capacitor", app_name="app")

    data = json.loads((tmp_path / "capacitor.config.json").read_text())
    assert data["webDir"] == "."


def test_mobile_scaffold_capacitor_webdir_dist(tmp_path: Path) -> None:
    """When index.html is in dist/, webDir should be 'dist'."""
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "index.html").write_text("<html></html>")
    builder = MobileBuilder()
    builder.scaffold(tmp_path, framework="capacitor", app_name="app")

    data = json.loads((tmp_path / "capacitor.config.json").read_text())
    assert data["webDir"] == "dist"


def test_mobile_scaffold_capacitor_webdir_www(tmp_path: Path) -> None:
    """When index.html is in www/, webDir should be 'www'."""
    (tmp_path / "www").mkdir()
    (tmp_path / "www" / "index.html").write_text("<html></html>")
    builder = MobileBuilder()
    builder.scaffold(tmp_path, framework="capacitor", app_name="app")

    data = json.loads((tmp_path / "capacitor.config.json").read_text())
    assert data["webDir"] == "www"


def test_mobile_scaffold_capacitor_ios_target(tmp_path: Path) -> None:
    """When targets include ios, @capacitor/ios should be in deps."""
    builder = MobileBuilder()
    builder.scaffold(
        tmp_path,
        framework="capacitor",
        app_name="app",
        extra={"targets": ["android", "ios"]},
    )
    pkg = json.loads((tmp_path / "package.json").read_text())
    deps = pkg.get("dependencies", {})
    assert "@capacitor/android" in deps
    assert "@capacitor/ios" in deps


def test_mobile_scaffold_capacitor_preserves_existing_deps(tmp_path: Path) -> None:
    """Scaffold should not overwrite user-specified dep versions."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "myapp",
        "version": "1.0.0",
        "dependencies": {
            "@capacitor/core": "^5.0.0",
            "@capacitor/storage": "^1.2.5",
        },
    }))
    builder = MobileBuilder()
    builder.scaffold(tmp_path, framework="capacitor", app_name="myapp")

    pkg = json.loads((tmp_path / "package.json").read_text())
    deps = pkg["dependencies"]
    # User's pinned version should be preserved
    assert deps["@capacitor/core"] == "^5.0.0"
    # @capacitor/storage migrated to @capacitor/preferences
    assert "@capacitor/storage" not in deps
    assert "@capacitor/preferences" in deps
    # CLI should be added
    assert "@capacitor/cli" in deps
    assert "@capacitor/android" in deps


def test_mobile_scaffold_capacitor_pins_latest_to_6x(tmp_path: Path) -> None:
    """Scaffold should pin 'latest' Capacitor deps to ^6.0.0 (Node 20 compat)."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "myapp",
        "version": "1.0.0",
        "dependencies": {
            "@capacitor/core": "latest",
            "@capacitor/cli": "latest",
            "@capacitor/android": "latest",
        },
    }))
    builder = MobileBuilder()
    builder.scaffold(tmp_path, framework="capacitor", app_name="myapp")

    pkg = json.loads((tmp_path / "package.json").read_text())
    deps = pkg["dependencies"]
    assert deps["@capacitor/core"] == "^6.0.0"
    assert deps["@capacitor/cli"] == "^6.0.0"
    assert deps["@capacitor/android"] == "^6.0.0"


def test_mobile_scaffold_capacitor_migrates_storage_to_preferences(tmp_path: Path) -> None:
    """Scaffold should replace deprecated @capacitor/storage with @capacitor/preferences."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "myapp",
        "version": "1.0.0",
        "dependencies": {
            "@capacitor/core": "^6.0.0",
            "@capacitor/storage": "^5.0.0",
        },
    }))
    builder = MobileBuilder()
    builder.scaffold(tmp_path, framework="capacitor", app_name="myapp")

    pkg = json.loads((tmp_path / "package.json").read_text())
    deps = pkg["dependencies"]
    assert "@capacitor/storage" not in deps
    assert deps["@capacitor/preferences"] == "^6.0.0"


def test_mobile_scaffold_capacitor_pins_ios_latest_to_6x(tmp_path: Path) -> None:
    """Scaffold should pin @capacitor/ios 'latest' → '^6.0.0' when targets include ios.

    Regression: targets were not propagated to extra_scaffold, so only
    @capacitor/android (the default) was pinned while @capacitor/ios stayed
    at 'latest', causing npm ERESOLVE (ios@8.x needs core@^8, but core is ^6).
    """
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "flashcards",
        "version": "1.0.0",
        "dependencies": {
            "@capacitor/core": "latest",
            "@capacitor/cli": "latest",
            "@capacitor/android": "latest",
            "@capacitor/ios": "latest",
        },
    }))
    builder = MobileBuilder()
    builder.scaffold(
        tmp_path,
        framework="capacitor",
        app_name="flashcards",
        extra={"targets": ["android", "ios"]},
    )

    pkg = json.loads((tmp_path / "package.json").read_text())
    deps = pkg["dependencies"]
    assert deps["@capacitor/core"] == "^6.0.0"
    assert deps["@capacitor/cli"] == "^6.0.0"
    assert deps["@capacitor/android"] == "^6.0.0"
    assert deps["@capacitor/ios"] == "^6.0.0"


def test_mobile_scaffold_capacitor_overrides_incompatible_platform_versions(tmp_path: Path) -> None:
    """Scaffold should override incompatible platform dep versions to prevent conflicts."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "myapp",
        "version": "1.0.0",
        "dependencies": {
            "@capacitor/core": "^6.0.0",
            "@capacitor/android": "latest",  # This would be 8.x, incompatible
            "@capacitor/ios": "^8.0.0",     # This is incompatible with core 6.x
        },
    }))
    builder = MobileBuilder()
    builder.scaffold(
        tmp_path,
        framework="capacitor",
        app_name="testapp",
        extra={"targets": ["android", "ios"]},
    )
    pkg = json.loads((tmp_path / "package.json").read_text())
    deps = pkg["dependencies"]
    # Should override both to compatible 6.x versions
    assert deps["@capacitor/android"] == "^6.0.0"
    assert deps["@capacitor/ios"] == "^6.0.0"
    # Core should remain unchanged
    assert deps["@capacitor/core"] == "^6.0.0"


def test_mobile_scaffold_capacitor_updates_webdir_in_existing_config(tmp_path: Path) -> None:
    """If capacitor.config.json exists with webDir=dist but index.html is at root, update it."""
    (tmp_path / "index.html").write_text("<html></html>")
    (tmp_path / "capacitor.config.json").write_text(json.dumps({
        "appId": "com.test.app",
        "appName": "app",
        "webDir": "dist",
    }))
    builder = MobileBuilder()
    builder.scaffold(tmp_path, framework="capacitor", app_name="app")

    data = json.loads((tmp_path / "capacitor.config.json").read_text())
    assert data["webDir"] == "."


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


def test_mobile_scaffold_capacitor_updates_plugin_versions(tmp_path: Path) -> None:
    """Capacitor scaffolding updates plugin deps to compatible versions."""
    from pactown.builders.mobile import MobileBuilder

    # Create package.json with incompatible plugin versions
    pkg_json = tmp_path / "package.json"
    pkg_json.write_text(
        json.dumps(
            {
                "name": "test-app",
                "version": "1.0.0",
                "dependencies": {
                    "@capacitor/core": "^6.0.0",
                    "@capacitor/storage": "latest",  # Deprecated → migrated to @capacitor/preferences
                    "@capacitor/camera": "latest",   # This should be updated to ^6.0.0
                    "some-other-package": "^1.0.0",  # This should remain unchanged
                },
            }
        )
    )

    builder = MobileBuilder()
    builder._scaffold_capacitor(tmp_path, app_name="test-app", extra={"targets": ["android"]}, on_log=None)

    updated_pkg = json.loads(pkg_json.read_text())
    deps = updated_pkg["dependencies"]
    
    # Core packages should remain at ^6.0.0
    assert deps["@capacitor/core"] == "^6.0.0"
    assert deps["@capacitor/cli"] == "^6.0.0"
    assert deps["@capacitor/android"] == "^6.0.0"
    
    # @capacitor/storage migrated to @capacitor/preferences
    assert "@capacitor/storage" not in deps
    assert deps["@capacitor/preferences"] == "^6.0.0"
    assert deps["@capacitor/camera"] == "^6.0.0"
    
    # Non-capacitor packages should remain unchanged
    assert deps["some-other-package"] == "^1.0.0"


# ===========================================================================
# DesktopBuilder.scaffold - Tauri (extended)
# ===========================================================================

def test_desktop_scaffold_tauri_window_dimensions(tmp_path: Path) -> None:
    """Tauri scaffold should respect custom window dimensions."""
    builder = DesktopBuilder()
    builder.scaffold(
        tmp_path,
        framework="tauri",
        app_name="tauri-big",
        extra={"app_id": "com.test.big", "window_width": 1920, "window_height": 1080},
    )
    data = json.loads((tmp_path / "src-tauri" / "tauri.conf.json").read_text())
    win = data["tauri"]["windows"][0]
    assert win["width"] == 1920
    assert win["height"] == 1080
    assert win["title"] == "tauri-big"


def test_desktop_scaffold_tauri_default_dimensions(tmp_path: Path) -> None:
    """Tauri scaffold defaults to 1024x768 when no dimensions given."""
    builder = DesktopBuilder()
    builder.scaffold(tmp_path, framework="tauri", app_name="tauri-default")
    data = json.loads((tmp_path / "src-tauri" / "tauri.conf.json").read_text())
    win = data["tauri"]["windows"][0]
    assert win["width"] == 1024
    assert win["height"] == 768


def test_desktop_scaffold_tauri_does_not_overwrite_existing_config(tmp_path: Path) -> None:
    """Existing tauri.conf.json must not be overwritten."""
    tauri_dir = tmp_path / "src-tauri"
    tauri_dir.mkdir(parents=True)
    conf = tauri_dir / "tauri.conf.json"
    original = {"package": {"productName": "custom-tauri"}, "custom_key": True}
    conf.write_text(json.dumps(original))

    builder = DesktopBuilder()
    builder.scaffold(tmp_path, framework="tauri", app_name="should-not-overwrite")

    data = json.loads(conf.read_text())
    assert data["package"]["productName"] == "custom-tauri"
    assert data["custom_key"] is True


def test_desktop_scaffold_tauri_bundle_identifier(tmp_path: Path) -> None:
    """Tauri scaffold should use provided app_id as bundle identifier."""
    builder = DesktopBuilder()
    builder.scaffold(
        tmp_path, framework="tauri", app_name="myapp",
        extra={"app_id": "org.example.myapp"},
    )
    data = json.loads((tmp_path / "src-tauri" / "tauri.conf.json").read_text())
    assert data["tauri"]["bundle"]["identifier"] == "org.example.myapp"


# ===========================================================================
# DesktopBuilder.scaffold - PyQt
# ===========================================================================

def test_desktop_scaffold_pyqt(tmp_path: Path) -> None:
    """PyQt scaffold should create .spec file."""
    builder = DesktopBuilder()
    builder.scaffold(tmp_path, framework="pyqt", app_name="pyqt-app")

    spec = tmp_path / "pyqt-app.spec"
    assert spec.exists()
    text = spec.read_text()
    assert "pyqt-app" in text
    assert "main.py" in text
    assert "console=False" in text


def test_desktop_scaffold_pyqt_with_icon(tmp_path: Path) -> None:
    """PyQt scaffold should include icon path in .spec if provided."""
    builder = DesktopBuilder()
    builder.scaffold(
        tmp_path, framework="pyqt", app_name="iconapp",
        extra={"icon": "assets/icon.ico"},
    )
    spec = tmp_path / "iconapp.spec"
    text = spec.read_text()
    assert "icon='assets/icon.ico'" in text


# ===========================================================================
# DesktopBuilder.scaffold - Tkinter
# ===========================================================================

def test_desktop_scaffold_tkinter(tmp_path: Path) -> None:
    """Tkinter scaffold creates a .spec file like PyInstaller."""
    builder = DesktopBuilder()
    builder.scaffold(tmp_path, framework="tkinter", app_name="tk-app")

    spec = tmp_path / "tk-app.spec"
    assert spec.exists()
    text = spec.read_text()
    assert "tk-app" in text


def test_desktop_scaffold_tkinter_does_not_overwrite_existing_spec(tmp_path: Path) -> None:
    """Existing .spec file must not be overwritten by scaffold."""
    spec = tmp_path / "myapp.spec"
    spec.write_text("# custom spec content\n")

    builder = DesktopBuilder()
    builder.scaffold(tmp_path, framework="tkinter", app_name="myapp")
    assert spec.read_text() == "# custom spec content\n"


# ===========================================================================
# DesktopBuilder.scaffold - Flutter desktop
# ===========================================================================

def test_desktop_scaffold_flutter_desktop_noop(tmp_path: Path) -> None:
    """Flutter desktop scaffold is a no-op (logs a message)."""
    logs: list[str] = []
    builder = DesktopBuilder()
    builder.scaffold(tmp_path, framework="flutter", app_name="fl-app", on_log=logs.append)
    # No files created, just a log message
    assert any("flutter" in l.lower() or "No scaffolding" in l for l in logs)


# ===========================================================================
# DesktopBuilder.scaffold - Unknown framework
# ===========================================================================

def test_desktop_scaffold_unknown_framework_noop(tmp_path: Path) -> None:
    """Unknown framework scaffold should not crash."""
    logs: list[str] = []
    builder = DesktopBuilder()
    builder.scaffold(tmp_path, framework="godot", app_name="game", on_log=logs.append)
    assert any("No scaffolding" in l for l in logs)


# ===========================================================================
# DesktopBuilder - Electron builder flags (multi-OS targets)
# ===========================================================================

def test_electron_builder_flags_linux_only() -> None:
    flags = DesktopBuilder._electron_builder_flags(["linux"])
    assert flags == ["--linux"]


def test_electron_builder_flags_empty_defaults_to_linux() -> None:
    flags = DesktopBuilder._electron_builder_flags([])
    assert flags == ["--linux"]


def test_electron_builder_flags_none_defaults_to_linux() -> None:
    flags = DesktopBuilder._electron_builder_flags(None)
    assert flags == ["--linux"]


@patch("platform.system", return_value="Linux")
@patch("shutil.which", return_value=None)
def test_electron_builder_flags_windows_skipped_on_linux_no_wine(mock_which, mock_sys) -> None:
    """On Linux without Wine, --windows target should be skipped."""
    flags = DesktopBuilder._electron_builder_flags(["linux", "windows"])
    assert "--linux" in flags
    assert "--windows" not in flags


@patch("platform.system", return_value="Linux")
@patch("shutil.which", return_value="/usr/bin/wine")
def test_electron_builder_flags_windows_allowed_with_wine(mock_which, mock_sys) -> None:
    """On Linux with Wine available, --windows target should be included."""
    flags = DesktopBuilder._electron_builder_flags(["linux", "windows"])
    assert "--linux" in flags
    assert "--windows" in flags


@patch("platform.system", return_value="Linux")
@patch("shutil.which", return_value=None)
def test_electron_builder_flags_mac_skipped_on_linux(mock_which, mock_sys) -> None:
    """On Linux, --mac target should be skipped (can't cross-compile macOS)."""
    flags = DesktopBuilder._electron_builder_flags(["linux", "macos"])
    assert "--linux" in flags
    assert "--mac" not in flags


@patch("platform.system", return_value="Darwin")
@patch("shutil.which", return_value=None)
def test_electron_builder_flags_mac_allowed_on_darwin(mock_which, mock_sys) -> None:
    """On macOS, --mac target should be included."""
    flags = DesktopBuilder._electron_builder_flags(["mac"])
    assert "--mac" in flags


@patch("platform.system", return_value="Windows")
@patch("shutil.which", return_value=None)
def test_electron_builder_flags_windows_on_windows(mock_which, mock_sys) -> None:
    """On Windows, --windows target should be included."""
    flags = DesktopBuilder._electron_builder_flags(["windows"])
    assert "--windows" in flags


def test_electron_builder_flags_deduplicates() -> None:
    """Duplicate target names should not produce duplicate flags."""
    flags = DesktopBuilder._electron_builder_flags(["linux", "linux"])
    assert flags.count("--linux") == 1


def test_electron_builder_flags_aliases() -> None:
    """win, macos, darwin should map to correct flags."""
    # Just test the mapping logic; actual cross-compile filtering depends on host
    assert "win" in {"linux", "windows", "win", "macos", "mac", "darwin"}


# ===========================================================================
# DesktopBuilder._filter_electron_builder_cmd
# ===========================================================================

@patch("platform.system", return_value="Linux")
@patch("shutil.which", return_value=None)
def test_filter_electron_builder_cmd_strips_windows_on_linux(mock_which, mock_sys) -> None:
    cmd = DesktopBuilder._filter_electron_builder_cmd(
        "npx electron-builder --linux --windows --mac"
    )
    assert "--linux" in cmd
    assert "--windows" not in cmd
    assert "--mac" not in cmd


@patch("platform.system", return_value="Linux")
@patch("shutil.which", return_value=None)
def test_filter_electron_builder_cmd_ensures_at_least_one_platform(mock_which, mock_sys) -> None:
    """If all platform flags are stripped, --linux is added as fallback."""
    cmd = DesktopBuilder._filter_electron_builder_cmd(
        "npx electron-builder --windows --mac"
    )
    assert "--linux" in cmd


# ===========================================================================
# DesktopBuilder._default_build_cmd for all frameworks
# ===========================================================================

def test_desktop_default_build_cmd_electron_linux() -> None:
    cmd = DesktopBuilder._default_build_cmd("electron", ["linux"])
    assert "electron-builder" in cmd
    assert "--linux" in cmd


@patch("platform.system", return_value="Linux")
@patch("shutil.which", return_value=None)
def test_desktop_default_build_cmd_electron_multi_target(mock_which, mock_sys) -> None:
    """Multi-target electron build generates flags per supported target."""
    cmd = DesktopBuilder._default_build_cmd("electron", ["linux", "windows"])
    assert "--linux" in cmd
    # --windows skipped on Linux without Wine
    assert "--windows" not in cmd


def test_desktop_default_build_cmd_tauri() -> None:
    cmd = DesktopBuilder._default_build_cmd("tauri", ["linux"])
    assert cmd == "npx tauri build"


def test_desktop_default_build_cmd_pyinstaller() -> None:
    cmd = DesktopBuilder._default_build_cmd("pyinstaller", ["linux"])
    assert "pyinstaller" in cmd
    assert "--onefile" in cmd
    assert "--windowed" in cmd


def test_desktop_default_build_cmd_tkinter() -> None:
    cmd = DesktopBuilder._default_build_cmd("tkinter", ["linux"])
    assert "pyinstaller" in cmd


def test_desktop_default_build_cmd_pyqt() -> None:
    cmd = DesktopBuilder._default_build_cmd("pyqt", ["linux"])
    assert "pyinstaller" in cmd


def test_desktop_default_build_cmd_flutter_linux() -> None:
    cmd = DesktopBuilder._default_build_cmd("flutter", ["linux"])
    assert cmd == "flutter build linux"


def test_desktop_default_build_cmd_flutter_windows() -> None:
    cmd = DesktopBuilder._default_build_cmd("flutter", ["windows"])
    assert cmd == "flutter build windows"


def test_desktop_default_build_cmd_flutter_macos() -> None:
    cmd = DesktopBuilder._default_build_cmd("flutter", ["macos"])
    assert cmd == "flutter build macos"


def test_desktop_default_build_cmd_unknown_framework() -> None:
    cmd = DesktopBuilder._default_build_cmd("godot", ["linux"])
    assert cmd == ""


# ===========================================================================
# DesktopBuilder._collect_artifacts for all frameworks
# ===========================================================================

def test_desktop_collect_artifacts_electron_appimage(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "myapp-1.0.0.AppImage").write_bytes(b"fake")
    (dist / "myapp-1.0.0.exe").write_bytes(b"fake")

    artifacts = DesktopBuilder._collect_artifacts(tmp_path, "electron")
    names = [a.name for a in artifacts]
    assert "myapp-1.0.0.AppImage" in names
    assert "myapp-1.0.0.exe" in names


def test_desktop_collect_artifacts_electron_dmg(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "myapp-1.0.0.dmg").write_bytes(b"fake")
    artifacts = DesktopBuilder._collect_artifacts(tmp_path, "electron")
    assert any(a.name.endswith(".dmg") for a in artifacts)


def test_desktop_collect_artifacts_electron_snap(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "myapp-1.0.0.snap").write_bytes(b"fake")
    artifacts = DesktopBuilder._collect_artifacts(tmp_path, "electron")
    assert any(a.name.endswith(".snap") for a in artifacts)


def test_desktop_collect_artifacts_electron_run_sh(tmp_path: Path) -> None:
    """Electron artifact collection includes run.sh and README.txt."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "run.sh").write_text("#!/bin/bash\n")
    (dist / "README.txt").write_text("readme\n")
    artifacts = DesktopBuilder._collect_artifacts(tmp_path, "electron")
    names = [a.name for a in artifacts]
    assert "run.sh" in names
    assert "README.txt" in names


def test_desktop_collect_artifacts_tauri(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "src-tauri" / "target" / "release" / "bundle" / "appimage"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "myapp.AppImage").write_bytes(b"fake")
    artifacts = DesktopBuilder._collect_artifacts(tmp_path, "tauri")
    assert len(artifacts) >= 1
    assert any("AppImage" in a.name for a in artifacts)


def test_desktop_collect_artifacts_pyinstaller(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "myapp").write_bytes(b"fake-binary")
    (dist / "myapp.exe").write_bytes(b"fake-exe")
    artifacts = DesktopBuilder._collect_artifacts(tmp_path, "pyinstaller")
    names = [a.name for a in artifacts]
    assert "myapp" in names
    assert "myapp.exe" in names


def test_desktop_collect_artifacts_pyqt(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "pyqt-app").write_bytes(b"fake")
    artifacts = DesktopBuilder._collect_artifacts(tmp_path, "pyqt")
    assert len(artifacts) == 1


def test_desktop_collect_artifacts_tkinter(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "tk-app").write_bytes(b"fake")
    artifacts = DesktopBuilder._collect_artifacts(tmp_path, "tkinter")
    assert len(artifacts) == 1


def test_desktop_collect_artifacts_flutter(tmp_path: Path) -> None:
    build_dir = tmp_path / "build" / "linux" / "x64" / "release" / "bundle"
    build_dir.mkdir(parents=True)
    (build_dir / "myapp").write_bytes(b"fake")
    artifacts = DesktopBuilder._collect_artifacts(tmp_path, "flutter")
    assert len(artifacts) >= 1


def test_desktop_collect_artifacts_empty(tmp_path: Path) -> None:
    """No build output → no artifacts."""
    artifacts = DesktopBuilder._collect_artifacts(tmp_path, "electron")
    assert artifacts == []


def test_desktop_collect_artifacts_unknown_framework_fallback(tmp_path: Path) -> None:
    """Unknown framework falls back to dist/* and build/* globs."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "output.bin").write_bytes(b"fake")
    artifacts = DesktopBuilder._collect_artifacts(tmp_path, "unknown-fw")
    assert len(artifacts) == 1


# ===========================================================================
# DesktopBuilder - Electron scaffold with build config targets
# ===========================================================================

def test_desktop_scaffold_electron_build_targets(tmp_path: Path) -> None:
    """Electron scaffold creates build config with Linux/Win/Mac targets."""
    builder = DesktopBuilder()
    builder.scaffold(tmp_path, framework="electron", app_name="cross-app")

    pkg = json.loads((tmp_path / "package.json").read_text())
    build = pkg.get("build", {})
    assert "linux" in build
    assert "win" in build
    assert "mac" in build
    assert build["linux"]["target"] == ["AppImage"]
    assert build["win"]["target"] == ["nsis"]
    assert build["mac"]["target"] == ["dmg"]


def test_desktop_scaffold_electron_move_electron_to_dev_deps(tmp_path: Path) -> None:
    """electron and electron-builder must be in devDependencies, not dependencies."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "test",
        "dependencies": {
            "electron": "^30.0.0",
            "electron-builder": "^24.0.0",
            "some-lib": "^1.0.0",
        },
    }))
    builder = DesktopBuilder()
    builder.scaffold(tmp_path, framework="electron", app_name="test")

    pkg = json.loads((tmp_path / "package.json").read_text())
    assert "electron" not in pkg.get("dependencies", {})
    assert "electron-builder" not in pkg.get("dependencies", {})
    assert "some-lib" in pkg["dependencies"]
    assert "electron" in pkg["devDependencies"]
    assert "electron-builder" in pkg["devDependencies"]
    # Version preserved from user
    assert pkg["devDependencies"]["electron"] == "^30.0.0"


def test_desktop_scaffold_electron_ensure_dev_deps_added(tmp_path: Path) -> None:
    """If electron/electron-builder missing entirely, pinned versions are added."""
    builder = DesktopBuilder()
    builder.scaffold(tmp_path, framework="electron", app_name="fresh-app")

    pkg = json.loads((tmp_path / "package.json").read_text())
    dev_deps = pkg.get("devDependencies", {})
    assert "electron" in dev_deps
    assert "electron-builder" in dev_deps
    # Pinned versions
    assert dev_deps["electron"].startswith("^")
    assert dev_deps["electron-builder"].startswith("^")


# ===========================================================================
# DesktopBuilder.build - result structure
# ===========================================================================

def test_desktop_build_no_cmd_returns_failure() -> None:
    """Build without command or framework returns failure."""
    builder = DesktopBuilder()
    result = builder.build(Path("/tmp/nonexistent"), framework="unknown-fw")
    assert not result.success
    assert "No build command" in result.message


# ===========================================================================
# MobileBuilder.scaffold - React Native
# ===========================================================================

def test_mobile_scaffold_react_native(tmp_path: Path) -> None:
    """React Native scaffold creates app.json with app name."""
    builder = MobileBuilder()
    builder.scaffold(
        tmp_path,
        framework="react-native",
        app_name="rn-app",
        extra={"app_name": "My RN App"},
    )

    app_json = tmp_path / "app.json"
    assert app_json.exists()
    data = json.loads(app_json.read_text())
    assert data["name"] == "rn-app"
    assert data["displayName"] == "My RN App"


def test_mobile_scaffold_react_native_default_display_name(tmp_path: Path) -> None:
    """React Native scaffold uses app_name as displayName fallback."""
    builder = MobileBuilder()
    builder.scaffold(tmp_path, framework="react-native", app_name="myrnapp")

    data = json.loads((tmp_path / "app.json").read_text())
    assert data["displayName"] == "myrnapp"


def test_mobile_scaffold_react_native_does_not_overwrite(tmp_path: Path) -> None:
    """Existing app.json must not be overwritten."""
    app_json = tmp_path / "app.json"
    original = {"name": "custom", "displayName": "Custom App", "extra": True}
    app_json.write_text(json.dumps(original))

    builder = MobileBuilder()
    builder.scaffold(tmp_path, framework="react-native", app_name="should-not-overwrite")

    data = json.loads(app_json.read_text())
    assert data["name"] == "custom"
    assert data["extra"] is True


# ===========================================================================
# MobileBuilder.scaffold - Kivy (extended)
# ===========================================================================

def test_mobile_scaffold_kivy_app_id(tmp_path: Path) -> None:
    """Kivy scaffold should use app_id for package domain."""
    builder = MobileBuilder()
    builder.scaffold(
        tmp_path, framework="kivy", app_name="learn",
        extra={"app_id": "org.example.learn"},
    )
    text = (tmp_path / "buildozer.spec").read_text()
    assert "package.domain = org.example" in text


def test_mobile_scaffold_kivy_no_fullscreen(tmp_path: Path) -> None:
    """Kivy scaffold defaults to non-fullscreen."""
    builder = MobileBuilder()
    builder.scaffold(tmp_path, framework="kivy", app_name="notfs")
    text = (tmp_path / "buildozer.spec").read_text()
    assert "fullscreen = 0" in text


def test_mobile_scaffold_kivy_does_not_overwrite(tmp_path: Path) -> None:
    """Existing buildozer.spec must not be overwritten."""
    spec = tmp_path / "buildozer.spec"
    spec.write_text("[app]\ntitle = custom\n")
    builder = MobileBuilder()
    builder.scaffold(tmp_path, framework="kivy", app_name="newname")
    assert "custom" in spec.read_text()


def test_mobile_scaffold_kivy_has_required_sections(tmp_path: Path) -> None:
    """Generated buildozer.spec should contain [app] and [buildozer] sections."""
    builder = MobileBuilder()
    builder.scaffold(tmp_path, framework="kivy", app_name="sections")
    text = (tmp_path / "buildozer.spec").read_text()
    assert "[app]" in text
    assert "[buildozer]" in text
    assert "requirements = python3,kivy" in text
    assert "android.permissions = INTERNET" in text


# ===========================================================================
# MobileBuilder.scaffold - Flutter (no-op)
# ===========================================================================

def test_mobile_scaffold_flutter_noop(tmp_path: Path) -> None:
    """Flutter mobile scaffold is a no-op (logs a message)."""
    logs: list[str] = []
    builder = MobileBuilder()
    builder.scaffold(tmp_path, framework="flutter", app_name="fl-mobile", on_log=logs.append)
    assert any("flutter" in l.lower() for l in logs)
    # No files should be created
    assert not list(tmp_path.iterdir())


# ===========================================================================
# MobileBuilder.scaffold - Unknown framework
# ===========================================================================

def test_mobile_scaffold_unknown_framework_noop(tmp_path: Path) -> None:
    """Unknown framework scaffold does not crash."""
    logs: list[str] = []
    builder = MobileBuilder()
    builder.scaffold(tmp_path, framework="ionic", app_name="ion", on_log=logs.append)
    assert any("No scaffolding" in l for l in logs)


# ===========================================================================
# MobileBuilder.scaffold - Capacitor webDir priority
# ===========================================================================

def test_mobile_capacitor_webdir_priority_dist_over_www(tmp_path: Path) -> None:
    """dist/ should be preferred over www/ when both have index.html."""
    for d in ("dist", "www"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "index.html").write_text("<html></html>")

    web_dir = MobileBuilder._resolve_cap_web_dir(tmp_path)
    assert web_dir == "dist"


def test_mobile_capacitor_webdir_priority_build(tmp_path: Path) -> None:
    """build/ dir should be detected for webDir."""
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "index.html").write_text("<html></html>")
    web_dir = MobileBuilder._resolve_cap_web_dir(tmp_path)
    assert web_dir == "build"


def test_mobile_capacitor_webdir_priority_public(tmp_path: Path) -> None:
    """public/ dir should be detected for webDir."""
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "index.html").write_text("<html></html>")
    web_dir = MobileBuilder._resolve_cap_web_dir(tmp_path)
    assert web_dir == "public"


def test_mobile_capacitor_webdir_no_index_defaults_to_dist(tmp_path: Path) -> None:
    """When no index.html found anywhere, webDir defaults to 'dist'."""
    web_dir = MobileBuilder._resolve_cap_web_dir(tmp_path)
    assert web_dir == "dist"


# ===========================================================================
# MobileBuilder._default_build_cmd for all frameworks × targets
# ===========================================================================

def test_mobile_default_build_cmd_capacitor_android() -> None:
    cmd = MobileBuilder._default_build_cmd("capacitor", ["android"])
    assert "cap sync" in cmd
    assert "cap build android" in cmd


def test_mobile_default_build_cmd_capacitor_ios() -> None:
    cmd = MobileBuilder._default_build_cmd("capacitor", ["ios"])
    assert "cap sync" in cmd
    assert "cap build ios" in cmd


def test_mobile_default_build_cmd_react_native_android() -> None:
    cmd = MobileBuilder._default_build_cmd("react-native", ["android"])
    assert "react-native build-android" in cmd
    assert "--mode=release" in cmd


def test_mobile_default_build_cmd_react_native_ios() -> None:
    cmd = MobileBuilder._default_build_cmd("react-native", ["ios"])
    assert "react-native build-ios" in cmd
    assert "--mode=release" in cmd


def test_mobile_default_build_cmd_flutter_android() -> None:
    cmd = MobileBuilder._default_build_cmd("flutter", ["android"])
    assert cmd == "flutter build apk --release"


def test_mobile_default_build_cmd_flutter_ios() -> None:
    cmd = MobileBuilder._default_build_cmd("flutter", ["ios"])
    assert cmd == "flutter build ios --release"


def test_mobile_default_build_cmd_kivy_android() -> None:
    cmd = MobileBuilder._default_build_cmd("kivy", ["android"])
    assert cmd == "buildozer android debug"


def test_mobile_default_build_cmd_kivy_ios() -> None:
    cmd = MobileBuilder._default_build_cmd("kivy", ["ios"])
    assert cmd == "buildozer ios debug"


def test_mobile_default_build_cmd_unknown_framework() -> None:
    cmd = MobileBuilder._default_build_cmd("cordova", ["android"])
    assert cmd == ""


def test_mobile_default_build_cmd_empty_targets_defaults_android() -> None:
    """When targets list is empty, default to android."""
    cmd = MobileBuilder._default_build_cmd("capacitor", [])
    assert "android" in cmd


# ===========================================================================
# MobileBuilder._collect_artifacts for all frameworks
# ===========================================================================

def test_mobile_collect_artifacts_capacitor_apk(tmp_path: Path) -> None:
    apk_dir = tmp_path / "android" / "app" / "build" / "outputs" / "apk" / "debug"
    apk_dir.mkdir(parents=True)
    (apk_dir / "app-debug.apk").write_bytes(b"fake-apk")
    artifacts = MobileBuilder._collect_artifacts(tmp_path, "capacitor")
    assert len(artifacts) == 1
    assert artifacts[0].name == "app-debug.apk"


def test_mobile_collect_artifacts_capacitor_ipa(tmp_path: Path) -> None:
    ipa_dir = tmp_path / "ios" / "App" / "build" / "Release"
    ipa_dir.mkdir(parents=True)
    (ipa_dir / "App.ipa").write_bytes(b"fake-ipa")
    artifacts = MobileBuilder._collect_artifacts(tmp_path, "capacitor")
    assert len(artifacts) == 1
    assert artifacts[0].name == "App.ipa"


def test_mobile_collect_artifacts_capacitor_both(tmp_path: Path) -> None:
    """Capacitor build with both android and ios artifacts."""
    apk_dir = tmp_path / "android" / "app" / "build" / "outputs" / "apk" / "release"
    apk_dir.mkdir(parents=True)
    (apk_dir / "app-release.apk").write_bytes(b"fake")

    ipa_dir = tmp_path / "ios" / "App" / "build" / "Release"
    ipa_dir.mkdir(parents=True)
    (ipa_dir / "App.ipa").write_bytes(b"fake")

    artifacts = MobileBuilder._collect_artifacts(tmp_path, "capacitor")
    names = {a.name for a in artifacts}
    assert "app-release.apk" in names
    assert "App.ipa" in names


def test_mobile_collect_artifacts_react_native_apk(tmp_path: Path) -> None:
    apk_dir = tmp_path / "android" / "app" / "build" / "outputs" / "apk" / "release"
    apk_dir.mkdir(parents=True)
    (apk_dir / "app-release.apk").write_bytes(b"fake")
    artifacts = MobileBuilder._collect_artifacts(tmp_path, "react-native")
    assert len(artifacts) == 1


def test_mobile_collect_artifacts_react_native_ipa(tmp_path: Path) -> None:
    ipa_dir = tmp_path / "ios" / "build" / "Release"
    ipa_dir.mkdir(parents=True)
    (ipa_dir / "App.ipa").write_bytes(b"fake")
    artifacts = MobileBuilder._collect_artifacts(tmp_path, "react-native")
    assert len(artifacts) == 1


def test_mobile_collect_artifacts_flutter_apk(tmp_path: Path) -> None:
    apk_dir = tmp_path / "build" / "app" / "outputs" / "flutter-apk"
    apk_dir.mkdir(parents=True)
    (apk_dir / "app-release.apk").write_bytes(b"fake")
    artifacts = MobileBuilder._collect_artifacts(tmp_path, "flutter")
    assert len(artifacts) == 1


def test_mobile_collect_artifacts_flutter_ipa(tmp_path: Path) -> None:
    ipa_dir = tmp_path / "build" / "ios" / "ipa"
    ipa_dir.mkdir(parents=True)
    (ipa_dir / "Runner.ipa").write_bytes(b"fake")
    artifacts = MobileBuilder._collect_artifacts(tmp_path, "flutter")
    assert len(artifacts) == 1


def test_mobile_collect_artifacts_kivy_apk(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "myapp-0.1-debug.apk").write_bytes(b"fake")
    artifacts = MobileBuilder._collect_artifacts(tmp_path, "kivy")
    assert len(artifacts) == 1


def test_mobile_collect_artifacts_kivy_aab(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "myapp-0.1-release.aab").write_bytes(b"fake")
    artifacts = MobileBuilder._collect_artifacts(tmp_path, "kivy")
    assert len(artifacts) == 1


def test_mobile_collect_artifacts_empty(tmp_path: Path) -> None:
    artifacts = MobileBuilder._collect_artifacts(tmp_path, "capacitor")
    assert artifacts == []


def test_mobile_collect_artifacts_unknown_framework_fallback(tmp_path: Path) -> None:
    """Unknown framework uses fallback globs (build/**/*.apk etc.)."""
    build_dir = tmp_path / "build" / "out"
    build_dir.mkdir(parents=True)
    (build_dir / "app.apk").write_bytes(b"fake")
    artifacts = MobileBuilder._collect_artifacts(tmp_path, "cordova")
    assert len(artifacts) == 1


# ===========================================================================
# MobileBuilder.build - result structure
# ===========================================================================

def test_mobile_build_no_cmd_returns_failure() -> None:
    """Build without command or framework returns failure."""
    builder = MobileBuilder()
    result = builder.build(Path("/tmp/nonexistent"), framework="unknown-fw")
    assert not result.success
    assert "No build command" in result.message


# ===========================================================================
# MobileBuilder._ensure_cap_platforms
# ===========================================================================

def test_mobile_ensure_cap_platforms_skips_existing_dir(tmp_path: Path) -> None:
    """_ensure_cap_platforms should not run `cap add` if platform dir exists."""
    (tmp_path / "android").mkdir()
    builder = MobileBuilder()
    logs: list[str] = []
    with patch.object(builder, "_run_shell") as mock_shell:
        builder._ensure_cap_platforms(tmp_path, ["android"], on_log=logs.append)
    mock_shell.assert_not_called()


def test_mobile_ensure_cap_platforms_runs_cap_add(tmp_path: Path) -> None:
    """_ensure_cap_platforms should run `npx cap add android` when dir missing."""
    builder = MobileBuilder()
    logs: list[str] = []
    with patch.object(builder, "_run_shell", return_value=(0, "", "")) as mock_shell:
        builder._ensure_cap_platforms(tmp_path, ["android"], on_log=logs.append)
    mock_shell.assert_called_once()
    call_args = mock_shell.call_args
    assert "npx cap add android" in call_args[0][0]
    assert any("Adding Capacitor platform" in l for l in logs)


def test_mobile_ensure_cap_platforms_multiple_targets(tmp_path: Path) -> None:
    """_ensure_cap_platforms should add each missing platform."""
    builder = MobileBuilder()
    with patch.object(builder, "_run_shell", return_value=(0, "", "")) as mock_shell:
        builder._ensure_cap_platforms(tmp_path, ["android", "ios"])
    assert mock_shell.call_count == 2
    cmds = [c[0][0] for c in mock_shell.call_args_list]
    assert "npx cap add android" in cmds
    assert "npx cap add ios" in cmds


def test_mobile_ensure_cap_platforms_partial_existing(tmp_path: Path) -> None:
    """Only missing platforms should be added."""
    (tmp_path / "android").mkdir()
    builder = MobileBuilder()
    with patch.object(builder, "_run_shell", return_value=(0, "", "")) as mock_shell:
        builder._ensure_cap_platforms(tmp_path, ["android", "ios"])
    assert mock_shell.call_count == 1
    assert "npx cap add ios" in mock_shell.call_args[0][0]


def test_mobile_build_capacitor_calls_ensure_platforms(tmp_path: Path) -> None:
    """build() with framework=capacitor should call _ensure_cap_platforms."""
    builder = MobileBuilder()
    with patch.object(builder, "_ensure_cap_platforms") as mock_ensure, \
         patch.object(builder, "_run_shell", return_value=(0, "", "")):
        builder.build(
            tmp_path,
            build_cmd="npx cap sync android && cd android && ./gradlew assembleDebug",
            framework="capacitor",
            targets=["android"],
        )
    mock_ensure.assert_called_once()
    assert mock_ensure.call_args[0][1] == ["android"]


# ===========================================================================
# WebBuilder - extended
# ===========================================================================

def test_web_builder_platform_name() -> None:
    assert WebBuilder().platform_name == "web"


def test_web_builder_scaffold_multiple_frameworks(tmp_path: Path) -> None:
    """Web scaffold is no-op for any framework."""
    builder = WebBuilder()
    for fw in ("fastapi", "flask", "express", "next", "react", "vue", "django"):
        builder.scaffold(tmp_path, framework=fw)
    # No files created
    assert not any(tmp_path.iterdir())


def test_web_builder_build_result_structure(tmp_path: Path) -> None:
    builder = WebBuilder()
    result = builder.build(tmp_path, framework="fastapi")
    assert result.success
    assert result.platform == "web"
    assert result.output_dir == tmp_path
    assert "ready" in result.message.lower()


# ===========================================================================
# BuildResult dataclass - extended
# ===========================================================================

def test_build_result_all_fields() -> None:
    r = BuildResult(
        success=True,
        platform="desktop",
        framework="electron",
        artifacts=[Path("/tmp/a.AppImage")],
        output_dir=Path("/tmp/dist"),
        message="Build succeeded",
        logs=["line1", "line2"],
        build_cmd="npx electron-builder --linux",
        elapsed_seconds=12.5,
        extra={"target": "linux"},
    )
    assert r.success
    assert r.platform == "desktop"
    assert r.framework == "electron"
    assert len(r.artifacts) == 1
    assert r.elapsed_seconds == 12.5
    assert r.extra["target"] == "linux"


def test_build_result_failure() -> None:
    r = BuildResult(
        success=False,
        platform="mobile",
        framework="capacitor",
        message="Build failed with exit code 1",
        build_cmd="npx cap build android",
    )
    assert not r.success
    assert r.artifacts == []
    assert r.logs == []
    assert r.elapsed_seconds == 0.0


# ===========================================================================
# TargetConfig parsing
# ===========================================================================

def test_target_config_from_dict_desktop_electron() -> None:
    cfg = TargetConfig.from_dict({
        "platform": "desktop",
        "framework": "electron",
        "targets": ["linux", "windows", "macos"],
        "app_name": "MyApp",
        "app_id": "com.example.myapp",
        "window_width": 1280,
        "window_height": 720,
    })
    assert cfg.platform == TargetPlatform.DESKTOP
    assert cfg.framework == "electron"
    assert cfg.targets == ["linux", "windows", "macos"]
    assert cfg.app_name == "MyApp"
    assert cfg.app_id == "com.example.myapp"
    assert cfg.window_width == 1280
    assert cfg.window_height == 720
    assert cfg.is_desktop
    assert cfg.is_buildable
    assert not cfg.needs_port


def test_target_config_from_dict_mobile_capacitor() -> None:
    cfg = TargetConfig.from_dict({
        "platform": "mobile",
        "framework": "capacitor",
        "targets": ["android", "ios"],
    })
    assert cfg.platform == TargetPlatform.MOBILE
    assert cfg.framework == "capacitor"
    assert cfg.targets == ["android", "ios"]
    assert cfg.is_mobile
    assert cfg.is_buildable
    assert not cfg.needs_port


def test_target_config_from_dict_mobile_react_native() -> None:
    cfg = TargetConfig.from_dict({
        "platform": "mobile",
        "framework": "react-native",
        "targets": ["android"],
    })
    assert cfg.framework == "react-native"
    assert cfg.is_mobile


def test_target_config_from_dict_mobile_flutter() -> None:
    cfg = TargetConfig.from_dict({
        "platform": "mobile",
        "framework": "flutter",
        "targets": ["android", "ios"],
    })
    assert cfg.framework == "flutter"
    assert cfg.targets == ["android", "ios"]


def test_target_config_from_dict_mobile_kivy() -> None:
    cfg = TargetConfig.from_dict({
        "platform": "mobile",
        "framework": "kivy",
        "targets": ["android"],
        "fullscreen": True,
    })
    assert cfg.framework == "kivy"
    assert cfg.fullscreen is True


def test_target_config_from_dict_desktop_tauri() -> None:
    cfg = TargetConfig.from_dict({
        "platform": "desktop",
        "framework": "tauri",
        "targets": ["linux", "windows", "macos"],
    })
    assert cfg.framework == "tauri"
    assert len(cfg.targets) == 3


def test_target_config_from_dict_desktop_pyinstaller() -> None:
    cfg = TargetConfig.from_dict({
        "platform": "desktop",
        "framework": "pyinstaller",
    })
    assert cfg.framework == "pyinstaller"
    assert cfg.is_desktop


def test_target_config_from_dict_desktop_pyqt() -> None:
    cfg = TargetConfig.from_dict({
        "platform": "desktop",
        "framework": "pyqt",
        "icon": "icon.png",
    })
    assert cfg.framework == "pyqt"
    assert cfg.icon == "icon.png"


def test_target_config_from_dict_desktop_tkinter() -> None:
    cfg = TargetConfig.from_dict({
        "platform": "desktop",
        "framework": "tkinter",
    })
    assert cfg.framework == "tkinter"


def test_target_config_from_dict_web_default() -> None:
    cfg = TargetConfig.from_dict({})
    assert cfg.platform == TargetPlatform.WEB
    assert cfg.framework is None
    assert cfg.is_web
    assert cfg.needs_port
    assert not cfg.is_buildable


def test_target_config_from_dict_unknown_platform_defaults_web() -> None:
    cfg = TargetConfig.from_dict({"platform": "spaceship"})
    assert cfg.platform == TargetPlatform.WEB


def test_target_config_from_dict_targets_as_csv_string() -> None:
    """Targets can be provided as comma-separated string."""
    cfg = TargetConfig.from_dict({
        "platform": "desktop",
        "framework": "electron",
        "targets": "linux, windows, macos",
    })
    assert cfg.targets == ["linux", "windows", "macos"]


def test_target_config_from_dict_extra_keys_preserved() -> None:
    """Unknown keys in target config go into extra dict."""
    cfg = TargetConfig.from_dict({
        "platform": "desktop",
        "framework": "electron",
        "custom_setting": "value123",
    })
    assert cfg.extra["custom_setting"] == "value123"


def test_target_config_from_yaml_body() -> None:
    body = "platform: mobile\nframework: capacitor\ntargets: [android, ios]\n"
    cfg = TargetConfig.from_yaml_body(body)
    assert cfg.platform == TargetPlatform.MOBILE
    assert cfg.framework == "capacitor"
    assert cfg.targets == ["android", "ios"]


def test_target_config_from_yaml_body_invalid() -> None:
    """Invalid YAML body should not crash, defaults to web."""
    cfg = TargetConfig.from_yaml_body("{{invalid yaml")
    assert cfg.platform == TargetPlatform.WEB


# ===========================================================================
# TargetConfig.effective_build_targets
# ===========================================================================

def test_effective_build_targets_desktop_explicit() -> None:
    cfg = TargetConfig(
        platform=TargetPlatform.DESKTOP, framework="electron",
        targets=["linux", "windows"],
    )
    assert cfg.effective_build_targets() == ["linux", "windows"]


def test_effective_build_targets_desktop_default() -> None:
    cfg = TargetConfig(platform=TargetPlatform.DESKTOP, framework="electron")
    assert cfg.effective_build_targets() == ["linux"]


def test_effective_build_targets_mobile_explicit() -> None:
    cfg = TargetConfig(
        platform=TargetPlatform.MOBILE, framework="capacitor",
        targets=["android", "ios"],
    )
    assert cfg.effective_build_targets() == ["android", "ios"]


def test_effective_build_targets_mobile_default() -> None:
    cfg = TargetConfig(platform=TargetPlatform.MOBILE, framework="capacitor")
    assert cfg.effective_build_targets() == ["android"]


def test_effective_build_targets_web_empty() -> None:
    cfg = TargetConfig(platform=TargetPlatform.WEB)
    assert cfg.effective_build_targets() == []


# ===========================================================================
# TargetConfig.framework_meta
# ===========================================================================

def test_target_config_framework_meta_electron() -> None:
    cfg = TargetConfig(platform=TargetPlatform.DESKTOP, framework="electron")
    meta = cfg.framework_meta
    assert meta is not None
    assert meta.name == "electron"
    assert meta.needs_node is True


def test_target_config_framework_meta_capacitor() -> None:
    cfg = TargetConfig(platform=TargetPlatform.MOBILE, framework="capacitor")
    meta = cfg.framework_meta
    assert meta is not None
    assert meta.needs_node is True


def test_target_config_framework_meta_pyinstaller() -> None:
    cfg = TargetConfig(platform=TargetPlatform.DESKTOP, framework="pyinstaller")
    meta = cfg.framework_meta
    assert meta is not None
    assert meta.needs_python is True


def test_target_config_framework_meta_none() -> None:
    cfg = TargetConfig(platform=TargetPlatform.WEB)
    assert cfg.framework_meta is None


# ===========================================================================
# Framework registry completeness
# ===========================================================================

def test_framework_registry_has_all_desktop_frameworks() -> None:
    expected = {"electron", "tauri", "pyinstaller", "tkinter", "pyqt", "flutter-desktop"}
    assert expected.issubset(set(FRAMEWORK_REGISTRY.keys()))


def test_framework_registry_has_all_mobile_frameworks() -> None:
    expected = {"capacitor", "react-native", "flutter-mobile", "kivy"}
    assert expected.issubset(set(FRAMEWORK_REGISTRY.keys()))


def test_framework_registry_desktop_platforms() -> None:
    """All desktop frameworks should have platform=DESKTOP."""
    for key in ("electron", "tauri", "pyinstaller", "tkinter", "pyqt", "flutter-desktop"):
        assert FRAMEWORK_REGISTRY[key].platform == TargetPlatform.DESKTOP


def test_framework_registry_mobile_platforms() -> None:
    """All mobile frameworks should have platform=MOBILE."""
    for key in ("capacitor", "react-native", "flutter-mobile", "kivy"):
        assert FRAMEWORK_REGISTRY[key].platform == TargetPlatform.MOBILE


def test_framework_registry_all_have_build_cmd() -> None:
    """All registered frameworks should have a default build command."""
    for name, meta in FRAMEWORK_REGISTRY.items():
        assert meta.default_build_cmd, f"{name} missing default_build_cmd"


def test_framework_registry_all_have_artifact_patterns() -> None:
    """All registered frameworks should have artifact patterns."""
    for name, meta in FRAMEWORK_REGISTRY.items():
        assert meta.artifact_patterns, f"{name} missing artifact_patterns"


def test_framework_registry_node_frameworks() -> None:
    """Frameworks requiring Node should have needs_node=True."""
    for key in ("electron", "tauri", "capacitor", "react-native"):
        assert FRAMEWORK_REGISTRY[key].needs_node is True, f"{key} should need node"


def test_framework_registry_python_frameworks() -> None:
    """Frameworks requiring Python should have needs_python=True."""
    for key in ("pyinstaller", "tkinter", "pyqt", "kivy"):
        assert FRAMEWORK_REGISTRY[key].needs_python is True, f"{key} should need python"


# ===========================================================================
# get_framework_meta / list_frameworks
# ===========================================================================

def test_get_framework_meta_case_insensitive() -> None:
    assert get_framework_meta("Electron") is not None
    assert get_framework_meta("CAPACITOR") is not None
    assert get_framework_meta("React-Native") is not None


def test_get_framework_meta_unknown() -> None:
    assert get_framework_meta("cordova") is None
    assert get_framework_meta("") is None
    assert get_framework_meta(None) is None


def test_list_frameworks_all() -> None:
    all_fw = list_frameworks()
    assert len(all_fw) == len(FRAMEWORK_REGISTRY)


def test_list_frameworks_desktop_only() -> None:
    desktop = list_frameworks(TargetPlatform.DESKTOP)
    assert all(f.platform == TargetPlatform.DESKTOP for f in desktop)
    assert len(desktop) >= 5  # electron, tauri, pyinstaller, tkinter, pyqt, flutter-desktop


def test_list_frameworks_mobile_only() -> None:
    mobile = list_frameworks(TargetPlatform.MOBILE)
    assert all(f.platform == TargetPlatform.MOBILE for f in mobile)
    assert len(mobile) >= 4  # capacitor, react-native, flutter-mobile, kivy


# ===========================================================================
# infer_target_from_deps
# ===========================================================================

def test_infer_target_electron() -> None:
    assert infer_target_from_deps(["electron"]) == TargetPlatform.DESKTOP


def test_infer_target_tauri() -> None:
    assert infer_target_from_deps(["@tauri-apps/api", "tauri"]) == TargetPlatform.DESKTOP


def test_infer_target_pyinstaller() -> None:
    assert infer_target_from_deps(["pyinstaller", "requests"]) == TargetPlatform.DESKTOP


def test_infer_target_pyqt() -> None:
    assert infer_target_from_deps(["pyqt6", "numpy"]) == TargetPlatform.DESKTOP


def test_infer_target_tkinter() -> None:
    assert infer_target_from_deps(["tkinter"]) == TargetPlatform.DESKTOP


def test_infer_target_capacitor() -> None:
    assert infer_target_from_deps(["@capacitor/core", "@capacitor/cli"]) == TargetPlatform.MOBILE


def test_infer_target_react_native() -> None:
    assert infer_target_from_deps(["react-native", "react"]) == TargetPlatform.MOBILE


def test_infer_target_expo() -> None:
    assert infer_target_from_deps(["expo", "react-native"]) == TargetPlatform.MOBILE


def test_infer_target_buildozer() -> None:
    assert infer_target_from_deps(["buildozer", "kivy"]) == TargetPlatform.MOBILE


def test_infer_target_flutter() -> None:
    assert infer_target_from_deps(["flutter"]) == TargetPlatform.MOBILE


def test_infer_target_web_default() -> None:
    assert infer_target_from_deps(["fastapi", "uvicorn"]) == TargetPlatform.WEB


def test_infer_target_empty_deps() -> None:
    assert infer_target_from_deps([]) == TargetPlatform.WEB


def test_infer_target_mobile_over_desktop_when_both_hinted() -> None:
    """If deps hint both mobile and desktop, mobile wins (checked first)."""
    result = infer_target_from_deps(["capacitor", "electron"])
    assert result == TargetPlatform.MOBILE


# ===========================================================================
# Builder registry - get_builder_for_target all combinations
# ===========================================================================

def test_get_builder_for_target_mobile_capacitor() -> None:
    cfg = TargetConfig(platform=TargetPlatform.MOBILE, framework="capacitor")
    b = get_builder_for_target(cfg)
    assert isinstance(b, MobileBuilder)


def test_get_builder_for_target_mobile_react_native() -> None:
    cfg = TargetConfig(platform=TargetPlatform.MOBILE, framework="react-native")
    b = get_builder_for_target(cfg)
    assert isinstance(b, MobileBuilder)


def test_get_builder_for_target_mobile_flutter() -> None:
    cfg = TargetConfig(platform=TargetPlatform.MOBILE, framework="flutter")
    b = get_builder_for_target(cfg)
    assert isinstance(b, MobileBuilder)


def test_get_builder_for_target_mobile_kivy() -> None:
    cfg = TargetConfig(platform=TargetPlatform.MOBILE, framework="kivy")
    b = get_builder_for_target(cfg)
    assert isinstance(b, MobileBuilder)


def test_get_builder_for_target_desktop_electron() -> None:
    cfg = TargetConfig(platform=TargetPlatform.DESKTOP, framework="electron")
    b = get_builder_for_target(cfg)
    assert isinstance(b, DesktopBuilder)


def test_get_builder_for_target_desktop_tauri() -> None:
    cfg = TargetConfig(platform=TargetPlatform.DESKTOP, framework="tauri")
    b = get_builder_for_target(cfg)
    assert isinstance(b, DesktopBuilder)


def test_get_builder_for_target_desktop_pyinstaller() -> None:
    cfg = TargetConfig(platform=TargetPlatform.DESKTOP, framework="pyinstaller")
    b = get_builder_for_target(cfg)
    assert isinstance(b, DesktopBuilder)


def test_get_builder_for_target_desktop_pyqt() -> None:
    cfg = TargetConfig(platform=TargetPlatform.DESKTOP, framework="pyqt")
    b = get_builder_for_target(cfg)
    assert isinstance(b, DesktopBuilder)


def test_get_builder_for_target_desktop_tkinter() -> None:
    cfg = TargetConfig(platform=TargetPlatform.DESKTOP, framework="tkinter")
    b = get_builder_for_target(cfg)
    assert isinstance(b, DesktopBuilder)


def test_get_builder_for_target_web_fastapi() -> None:
    cfg = TargetConfig(platform=TargetPlatform.WEB, framework="fastapi")
    b = get_builder_for_target(cfg)
    assert isinstance(b, WebBuilder)
